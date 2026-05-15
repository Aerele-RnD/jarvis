import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from jarvis.exceptions import InvalidArgumentError

# Maps the Jarvis Settings llm_provider select option (human label) to openclaw's provider id.
# openclaw resolves the runtime adapter from the bundled plugin manifest; no "type" field is needed.
PROVIDER_MAP: dict[str, str] = {
    "Anthropic": "anthropic",
    "OpenAI": "openai",
    "Google Gemini": "google",
    "Mistral": "mistral",
    "Groq": "groq",
    "Together AI": "together",
    "DeepSeek": "deepseek",
    "Moonshot (Kimi)": "moonshot",
    "OpenRouter": "openrouter",
    "Ollama (local)": "ollama",
    "vLLM (local)": "vllm",
    "OpenAI-Compatible": "openai_compat",
}

# Fallback rendering when Jarvis Settings has no LLM provider configured yet — openclaw
# still boots so the rest of the pipeline (secrets.reload, restart) is reachable; actual
# LLM calls will 401 until the customer fills in real credentials.
STUB_DEFAULTS = {
    "provider_id": "moonshot",
    "model": "kimi-k2.6",
}

_TEMPLATE_DIR = Path(__file__).parent / "openclaw_templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
)


def render_config(settings, gateway_token: str) -> str:
    """Render openclaw.json from Jarvis Settings.

    `settings` is a Jarvis Settings doc (or duck-typed equivalent) with attributes:
    `llm_provider`, `llm_model`, `llm_base_url`.

    Falls back to STUB_DEFAULTS when no provider is configured so openclaw still
    boots. Raises InvalidArgumentError if a configured provider isn't in PROVIDER_MAP.
    """
    if not gateway_token:
        raise InvalidArgumentError("gateway_token is required")

    provider_label = getattr(settings, "llm_provider", None)
    model = getattr(settings, "llm_model", None)

    if not provider_label or not model:
        provider_id = STUB_DEFAULTS["provider_id"]
        model = STUB_DEFAULTS["model"]
        base_url = None
    else:
        if provider_label not in PROVIDER_MAP:
            raise InvalidArgumentError(f"unknown llm_provider: {provider_label!r}")
        provider_id = PROVIDER_MAP[provider_label]
        base_url = getattr(settings, "llm_base_url", None) or None

    template = _env.get_template("openclaw.json.j2")
    rendered = template.render(
        gateway_token=gateway_token,
        provider_id=provider_id,
        model=model,
        base_url=base_url,
    )

    # Sanity: ensure the rendered output is valid JSON (the {% if base_url %} block
    # can introduce a trailing comma if we're not careful with Jinja whitespace).
    try:
        json.loads(rendered)
    except json.JSONDecodeError as e:
        raise InvalidArgumentError(f"template rendered invalid JSON: {e}") from e
    return rendered
