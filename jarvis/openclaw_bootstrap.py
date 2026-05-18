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

# Workspace persona seeds — shipped with the app at openclaw_workspace_seeds/.
# Copied into the agent workspace on bootstrap so a fresh container boots as
# "Jarvis" instead of the openclaw default identity ritual.
WORKSPACE_SEED_DIR = Path(__file__).parent / "openclaw_workspace_seeds"
WORKSPACE_SEED_FILES = ("IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md")

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
        "agent_workspace_dir": state_dir / "workspace",
        "env_path": state_dir / ".env",
    }


def _seed_workspace(agent_workspace_dir: Path) -> None:
    """Copy Jarvis persona seeds (IDENTITY/SOUL/AGENTS/USER) into the agent
    workspace, but only files that don't already exist.

    Why "only if missing": openclaw and the agent itself write back to these
    files (memory, learned preferences). Overwriting would erase that. The
    seeds are a first-run identity, not a config to be re-applied.

    Also removes a stale ``BOOTSTRAP.md`` if our seeds are present — the
    bootstrap ritual is only meaningful for a workspace with no identity,
    and we've already provided one.
    """
    import shutil

    agent_workspace_dir.mkdir(parents=True, exist_ok=True)
    for fname in WORKSPACE_SEED_FILES:
        src = WORKSPACE_SEED_DIR / fname
        dst = agent_workspace_dir / fname
        if src.exists() and not dst.exists():
            shutil.copyfile(src, dst)

    bootstrap = agent_workspace_dir / "BOOTSTRAP.md"
    if bootstrap.exists() and (agent_workspace_dir / "IDENTITY.md").exists():
        bootstrap.unlink()


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

    # Copy what openclaw needs: package.json, openclaw.plugin.json, dist/, and
    # the runtime dependencies the plugin imports at load time (e.g. typebox
    # for tool schemas). node_modules is copied fresh to track the host's
    # pnpm-installed versions.
    for fname in ("package.json", "openclaw.plugin.json"):
        src_file = source / fname
        if src_file.exists():
            shutil.copyfile(src_file, target / fname)

    target_dist = target / "dist"
    if target_dist.exists():
        shutil.rmtree(target_dist)
    shutil.copytree(dist, target_dist)

    # Copy production runtime dependencies into the install target's
    # node_modules/. Listed explicitly because pnpm uses a symlink farm that
    # naive copying would either dereference (pulling in the entire openclaw
    # source via the link: dep) or preserve broken (the symlink targets don't
    # exist inside the container). Keep this list in sync with the "dependencies"
    # block in jarvis-openclaw-plugin/package.json.
    runtime_deps = ("typebox",)
    src_node_modules = source / "node_modules"
    target_node_modules = target / "node_modules"
    if target_node_modules.exists():
        shutil.rmtree(target_node_modules)
    target_node_modules.mkdir(parents=True, exist_ok=True)
    for dep in runtime_deps:
        dep_src = (src_node_modules / dep).resolve()
        if not dep_src.exists():
            raise OpenclawRestartFailedError(
                f"plugin runtime dep '{dep}' not installed; "
                f"run `pnpm install` in {source} before bootstrap.start"
            )
        shutil.copytree(dep_src, target_node_modules / dep, symlinks=False)


def _write_env_file(
    env_path: Path,
    state_dir: Path,
    agent_workspace_dir: Path,
    gateway_token: str = "",
    site_name: str = "jarvis.localhost",
) -> None:
    """Write the .env file used by docker compose for variable interpolation.

    Also writes plugin callback env vars to the compose dir's .env so they are
    injected into the container process via docker-compose.yml's `env_file: path: .env`.

    ``OPENCLAW_WORKSPACE_DIR`` overrides the default ``~/.openclaw/workspace``
    so the agent's persona files (seeded under ``openclaw_state/workspace/``)
    are what the container sees on boot.
    """
    # Primary .env — used for docker compose variable substitution (${VAR} in yml).
    content = (
        f"OPENCLAW_CONFIG_DIR={state_dir.resolve()}\n"
        f"OPENCLAW_WORKSPACE_DIR={agent_workspace_dir.resolve()}\n"
        f"OPENCLAW_IMAGE={DEFAULT_IMAGE}\n"
        f"OPENCLAW_GATEWAY_PORT={DEFAULT_GATEWAY_PORT}\n"
        f"OPENCLAW_GATEWAY_BIND={DEFAULT_GATEWAY_BIND}\n"
        # Plugin env vars: allow the jarvis-openclaw-plugin to call into Frappe's
        # jarvis.api.call_tool, authenticated by JARVIS_GATEWAY_TOKEN.
        f"JARVIS_FRAPPE_URL=http://host.docker.internal:8000\n"
        f"JARVIS_GATEWAY_TOKEN={gateway_token}\n"
        f"JARVIS_SITE_NAME={site_name}\n"
    )
    env_path.write_text(content)


def _write_plugin_env(compose_env_path: Path, gateway_token: str = "", site_name: str = "jarvis.localhost") -> None:
    """Write JARVIS_* env vars to the compose directory's .env file.

    docker-compose.yml has `env_file: path: .env` which injects all vars from
    this file directly into the container process. This is how JARVIS_FRAPPE_URL,
    JARVIS_GATEWAY_TOKEN, and JARVIS_SITE_NAME become available to the plugin
    at runtime inside the container.
    """
    content = (
        f"JARVIS_FRAPPE_URL=http://host.docker.internal:8000\n"
        f"JARVIS_GATEWAY_TOKEN={gateway_token}\n"
        f"JARVIS_SITE_NAME={site_name}\n"
    )
    compose_env_path.write_text(content)


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

    # Seed the agent workspace with Jarvis persona files so the container boots
    # already knowing who it is. Idempotent: only writes missing files.
    _seed_workspace(paths["agent_workspace_dir"])

    rendered = render_config(settings, token)
    paths["config_path"].write_text(rendered)

    # Write env file with plugin callback vars so jarvis-openclaw-plugin can
    # reach Frappe's jarvis.api.call_tool, authenticated by the gateway token.
    _write_env_file(
        paths["env_path"],
        paths["state_dir"],
        paths["agent_workspace_dir"],
        gateway_token=token,
    )

    # Also write a .env in the compose dir so docker-compose.yml's
    # `env_file: path: .env` injects JARVIS_* vars into the container process.
    # The compose dir's .env is what the container actually reads at startup.
    compose_env_path = paths["compose_dir"] / ".env"
    _write_plugin_env(compose_env_path, gateway_token=token)

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
