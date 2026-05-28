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

# Default baseUrl per provider. openclaw's config schema requires baseUrl to be
# present on every models.providers.<id> entry even when the bundled plugin has
# a default — the plugin default isn't a substitute for the JSON field. Customers
# can override these by filling in `llm_base_url` on Jarvis Settings (required for
# vllm and openai_compat where we have no usable default).
PROVIDER_DEFAULT_BASE_URLS: dict[str, str | None] = {
	"Anthropic": "https://api.anthropic.com",
	"OpenAI": "https://api.openai.com/v1",
	"Google Gemini": "https://generativelanguage.googleapis.com",
	"Mistral": "https://api.mistral.ai/v1",
	"Groq": "https://api.groq.com/openai/v1",
	"Together AI": "https://api.together.xyz/v1",
	"DeepSeek": "https://api.deepseek.com",
	"Moonshot (Kimi)": "https://api.moonshot.ai/v1",
	"OpenRouter": "https://openrouter.ai/api/v1",
	"Ollama (local)": "http://host.docker.internal:11434/v1",
	"vLLM (local)": None,
	"OpenAI-Compatible": None,
}

# Fallback rendering when Jarvis Settings has no LLM provider configured yet — openclaw
# still boots so the rest of the pipeline (secrets.reload, restart) is reachable; actual
# LLM calls will 401 until the customer fills in real credentials.
STUB_DEFAULTS = {
	"provider_id": "moonshot",
	"model": "kimi-k2.6",
	"base_url": "https://api.moonshot.ai/v1",
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
	boots. Raises InvalidArgumentError if a configured provider isn't in PROVIDER_MAP,
	or if the provider has no default baseUrl and the customer hasn't supplied one.
	"""
	if not gateway_token:
		raise InvalidArgumentError("gateway_token is required")

	provider_label = getattr(settings, "llm_provider", None)
	model = getattr(settings, "llm_model", None)
	customer_base_url = (getattr(settings, "llm_base_url", None) or "").strip() or None
	auth_mode = getattr(settings, "llm_auth_mode", None) or "api_key"

	# Subscription mode with no access token yet → fall through to stub so the
	# container still boots; the cron / wizard will populate the token shortly.
	if auth_mode == "subscription":
		access_token = getattr(settings, "llm_oauth_access_token", None)
		if not access_token:
			provider_label = None
			auth_mode = "api_key"  # stub uses api_key shape

	if not provider_label or not model:
		provider_id = STUB_DEFAULTS["provider_id"]
		model = STUB_DEFAULTS["model"]
		base_url = STUB_DEFAULTS["base_url"]
		auth_mode = "api_key"
	else:
		if provider_label not in PROVIDER_MAP:
			raise InvalidArgumentError(f"unknown llm_provider: {provider_label!r}")
		provider_id = PROVIDER_MAP[provider_label]
		base_url = customer_base_url or PROVIDER_DEFAULT_BASE_URLS.get(provider_label)
		if not base_url:
			raise InvalidArgumentError(
				f"llm_base_url is required for provider {provider_label!r} (no default available)"
			)

	template = _env.get_template("openclaw.json.j2")
	rendered = template.render(
		gateway_token=gateway_token,
		provider_id=provider_id,
		model=model,
		base_url=base_url,
		auth_mode=auth_mode,
	)

	try:
		json.loads(rendered)
	except json.JSONDecodeError as e:
		raise InvalidArgumentError(f"template rendered invalid JSON: {e}") from e
	return rendered
