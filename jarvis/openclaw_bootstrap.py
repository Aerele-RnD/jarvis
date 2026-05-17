import json
import os
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path

import frappe

from jarvis.exceptions import OpenclawRestartFailedError
from jarvis.openclaw_config import render_config

PLUGIN_SOURCE_REL = "jarvis-openclaw-plugin"
PLUGIN_INSTALL_DIR_NAME = "jarvis-openclaw-plugin"

DEFAULT_GATEWAY_URL = "ws://127.0.0.1:18789"
DEFAULT_IMAGE = "ghcr.io/openclaw/openclaw:latest"
DEFAULT_GATEWAY_PORT = 18789
DEFAULT_GATEWAY_BIND = "lan"

HEALTHZ_URL = "http://127.0.0.1:18789/healthz"
HEALTHZ_TIMEOUT_SECONDS = 60
HEALTHZ_INTERVAL_SECONDS = 1

PULL_TIMEOUT_SECONDS = 600   # first-run image pull can be slow
COMPOSE_TIMEOUT_SECONDS = 60

# Placeholder written to llm.key on first bootstrap so openclaw can boot.
# Openclaw's SecretRef resolver fails-fast on empty values; the customer's
# first save in Jarvis Settings overwrites this file with a real key.
LLM_KEY_PLACEHOLDER = "PLACEHOLDER-set-llm_api_key-in-Jarvis-Settings"


def _workspace_root() -> Path:
    """Workspace root: the parent of the Frappe bench directory."""
    return Path(frappe.utils.get_bench_path()).parent


def _settings():
    return frappe.get_single("Jarvis Settings")


def _set_default_paths(settings) -> dict:
    """Populate operator-tab fields with defaults if they're empty. Returns the resolved paths."""
    workspace = _workspace_root()
    state_dir = workspace / "openclaw_state"
    compose_dir = workspace / "openclaw"
    config_path = state_dir / "openclaw.json"
    llm_key_path = state_dir / "llm.key"

    defaults = {
        "openclaw_compose_dir": str(compose_dir),
        "openclaw_config_path": str(config_path),
        "openclaw_llm_key_path": str(llm_key_path),
        "openclaw_gateway_url": DEFAULT_GATEWAY_URL,
    }
    for field, value in defaults.items():
        if not getattr(settings, field, None):
            settings.db_set(field, value)

    # Reload settings to see the values we just wrote
    settings.reload()
    return {
        "workspace": workspace,
        "state_dir": state_dir,
        "compose_dir": Path(settings.openclaw_compose_dir),
        "config_path": Path(settings.openclaw_config_path),
        "llm_key_path": Path(settings.openclaw_llm_key_path),
        "env_path": state_dir / ".env",
    }


def _ensure_gateway_token(settings) -> str:
    token = settings.get_password("openclaw_gateway_token") if settings.openclaw_gateway_token else None
    if not token:
        token = secrets.token_urlsafe(32)
        settings.db_set("openclaw_gateway_token", token)
        settings.reload()
        token = settings.get_password("openclaw_gateway_token")
    return token


def _install_plugin(workspace: Path, state_dir: Path) -> None:
    """Copy the built plugin into openclaw's extensions directory.

    Reads from <workspace>/jarvis-openclaw-plugin/{package.json, openclaw.plugin.json, dist/}
    and writes to <state_dir>/extensions/<plugin>/. Skips node_modules, tests, src, .git.
    Raises OpenclawRestartFailedError if the plugin's dist/ hasn't been built yet.
    """
    import shutil

    source = workspace / PLUGIN_SOURCE_REL
    if not source.exists():
        raise OpenclawRestartFailedError(
            f"plugin source not found at {source}; "
            f"is the jarvis-openclaw-plugin repo cloned alongside app/?"
        )
    dist = source / "dist"
    if not dist.exists() or not (dist / "index.js").exists():
        raise OpenclawRestartFailedError(
            f"plugin not built; run `pnpm install && pnpm build` in {source} first"
        )

    target = state_dir / "extensions" / PLUGIN_INSTALL_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)

    # Copy only what openclaw needs: package.json, openclaw.plugin.json, dist/
    for fname in ("package.json", "openclaw.plugin.json"):
        src_file = source / fname
        if src_file.exists():
            shutil.copyfile(src_file, target / fname)

    target_dist = target / "dist"
    if target_dist.exists():
        shutil.rmtree(target_dist)
    shutil.copytree(dist, target_dist)


def _write_env_file(env_path: Path, state_dir: Path) -> None:
    content = (
        f"OPENCLAW_CONFIG_DIR={state_dir.resolve()}\n"
        f"OPENCLAW_IMAGE={DEFAULT_IMAGE}\n"
        f"OPENCLAW_GATEWAY_PORT={DEFAULT_GATEWAY_PORT}\n"
        f"OPENCLAW_GATEWAY_BIND={DEFAULT_GATEWAY_BIND}\n"
    )
    env_path.write_text(content)


def _poll_healthz() -> None:
    """Poll the gateway healthz endpoint until 2xx or timeout."""
    deadline = time.monotonic() + HEALTHZ_TIMEOUT_SECONDS
    last_err = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTHZ_URL, timeout=2) as r:
                if 200 <= r.status < 300:
                    return
                last_err = f"HTTP {r.status}"
        except Exception as e:
            last_err = str(e)
        time.sleep(HEALTHZ_INTERVAL_SECONDS)
    raise OpenclawRestartFailedError(f"openclaw gateway never became healthy: {last_err}")


def start() -> None:
    """Provision openclaw state files and start the container. Safe to re-run."""
    settings = _settings()
    paths = _set_default_paths(settings)
    settings = _settings()  # reload after db_set
    token = _ensure_gateway_token(settings)
    settings = _settings()  # reload after token write

    paths["state_dir"].mkdir(parents=True, exist_ok=True)

    # Create a placeholder llm.key only if missing — preserve any real key written
    # by on_update. The placeholder must be non-empty: openclaw's SecretRef resolver
    # treats empty values as "unresolved" and refuses to boot. The customer's first
    # save of Jarvis Settings with a real LLM API key overwrites this file via the
    # on_update hook.
    if not paths["llm_key_path"].exists():
        paths["llm_key_path"].write_text(LLM_KEY_PLACEHOLDER)
        os.chmod(paths["llm_key_path"], 0o600)

    # Install the plugin into openclaw's extensions directory before rendering config
    # (the config references the plugin by id). Idempotent: overwrites on every start().
    _install_plugin(paths["workspace"], paths["state_dir"])

    rendered = render_config(settings, token)
    paths["config_path"].write_text(rendered)

    _write_env_file(paths["env_path"], paths["state_dir"])

    # docker compose pull
    pull_cmd = [
        "docker", "compose",
        "-f", str(paths["compose_dir"] / "docker-compose.yml"),
        "--env-file", str(paths["env_path"]),
        "pull", "openclaw-gateway",
    ]
    try:
        subprocess.run(pull_cmd, check=True, capture_output=True, text=True, timeout=PULL_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as e:
        raise OpenclawRestartFailedError(f"docker compose pull failed: {e.stderr or e}") from e
    except subprocess.TimeoutExpired as e:
        raise OpenclawRestartFailedError(f"docker compose pull timed out: {e}") from e

    # docker compose up -d
    up_cmd = [
        "docker", "compose",
        "-f", str(paths["compose_dir"] / "docker-compose.yml"),
        "--env-file", str(paths["env_path"]),
        "up", "-d", "openclaw-gateway",
    ]
    try:
        subprocess.run(up_cmd, check=True, capture_output=True, text=True, timeout=COMPOSE_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as e:
        raise OpenclawRestartFailedError(f"docker compose up failed: {e.stderr or e}") from e
    except subprocess.TimeoutExpired as e:
        raise OpenclawRestartFailedError(f"docker compose up timed out: {e}") from e

    _poll_healthz()

    settings.db_set({
        "last_sync_at": frappe.utils.now(),
        "last_sync_status": "openclaw started",
    })


def stop() -> None:
    """Stop the openclaw container via docker compose down."""
    settings = _settings()
    compose_dir = settings.openclaw_compose_dir or str(_workspace_root() / "openclaw")
    state_dir = Path(settings.openclaw_config_path).parent if settings.openclaw_config_path else (_workspace_root() / "openclaw_state")
    env_path = state_dir / ".env"

    cmd = ["docker", "compose", "-f", f"{compose_dir}/docker-compose.yml"]
    if env_path.exists():
        cmd.extend(["--env-file", str(env_path)])
    cmd.append("down")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=COMPOSE_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as e:
        raise OpenclawRestartFailedError(f"docker compose down failed: {e.stderr or e}") from e
    except subprocess.TimeoutExpired as e:
        raise OpenclawRestartFailedError(f"docker compose down timed out: {e}") from e

    settings.db_set("last_sync_status", "openclaw stopped")


def status() -> dict:
    """Return a dict describing the openclaw container + health state."""
    settings = _settings()
    compose_dir = settings.openclaw_compose_dir or str(_workspace_root() / "openclaw")

    container_state = "not_created"
    image = None
    cmd = [
        "docker", "compose",
        "-f", f"{compose_dir}/docker-compose.yml",
        "ps", "openclaw-gateway", "--format", "json",
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10)
        stdout = (result.stdout or "").strip()
        if stdout:
            # `docker compose ps --format json` returns either an object or one-object-per-line
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                # Try as JSON-lines: take first line
                parsed = json.loads(stdout.splitlines()[0])
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
            state = (parsed.get("State") or "").lower()
            container_state = state or container_state
            image = parsed.get("Image")
    except Exception:
        container_state = "not_created"

    health = "unknown"
    try:
        with urllib.request.urlopen(HEALTHZ_URL, timeout=2) as r:
            health = "healthy" if 200 <= r.status < 300 else "unhealthy"
    except Exception:
        health = "unhealthy" if container_state == "running" else "unknown"

    info = {
        "container": container_state,
        "image": image,
        "health": health,
        "gateway_url": "http://127.0.0.1:18789",
    }
    print(json.dumps(info, indent=2))
    return info


def restart() -> None:
    """Stop and then start. Re-renders config from current Settings."""
    try:
        stop()
    except OpenclawRestartFailedError:
        # If stop fails because the container wasn't running, that's OK — proceed to start.
        pass
    start()
