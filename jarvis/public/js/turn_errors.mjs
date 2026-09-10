// Shared by desktop, Desk and mobile. Python reads the same ordered rules.
import rules from "./turn_error_rules.mjs";

const compiled = rules.map((rule) => ({
  ...rule,
  test: new RegExp(rule.pattern, "i"),
}));
const byCode = Object.fromEntries(compiled.map((rule) => [rule.code, rule]));
const MAX_CLASSIFY_CHARS = 8192;
// Routing / inference hosts: when one of these is named it is the provider
// that answered, whatever model brand the text also mentions.
const HOSTS = new Set(["openrouter", "groq", "together"]);
// Official status destinations only; never turn a URL in an error into a link.
// An OpenAI-compatible endpoint does not identify OpenAI as the provider.
const providers = [
  [
    "openrouter",
    "OpenRouter",
    "https://status.openrouter.ai/",
    /\bopenrouter\b/i,
  ],
  ["groq", "Groq", "https://groqstatus.com/", /\bgroq\b/i],
  [
    "together",
    "Together AI",
    "https://status.together.ai/",
    // Suffix is mandatory: bare "together" is ordinary prose ("all retries
    // failed together"), and this entry outranks model-author matches.
    /\btogether(?:\.ai|\s?ai|computer)\b/i,
  ],
  [
    "anthropic",
    "Claude",
    "https://status.claude.com/",
    /\b(anthropic|claude)\b/i,
  ],
  [
    "openai",
    "OpenAI / ChatGPT",
    "https://status.openai.com/",
    /\b(openai(?![_ -]compat)|chatgpt|codex)\b/i,
  ],
  [
    "google",
    "Google Gemini",
    "https://aistudio.google.com/status",
    /\b(google|gemini)\b/i,
  ],
  ["mistral", "Mistral AI", "https://status.mistral.ai/", /\bmistral\b/i],
  ["deepseek", "DeepSeek", "https://status.deepseek.com/", /\bdeepseek\b/i],
  ["xai", "xAI", "https://status.x.ai/", /\b(xai|x\.ai|grok)\b/i],
  [
    "moonshot",
    "Moonshot / Kimi",
    "https://status.moonshot.cn/",
    /\b(moonshot|kimi)\b/i,
  ],
];
function providerFor(raw, context) {
  // Persisted actual provider outranks model names (e.g. Claude via OpenRouter).
  if (context?.provider) {
    const id = String(context.provider).toLowerCase();
    return providers.find(
      ([key]) =>
        key === id ||
        (key === "google" && id === "gemini") ||
        (key === "openai" && id === "openai-codex")
    );
  }
  // Do not infer a hosting company from a model name alone or the current
  // model picker: failover may have used a different connection for this run.
  if (/openai[_ -]compat|\b(ollama|vllm|azure|bedrock|vertex)\b/i.test(raw))
    return;
  const matches = providers.filter(([, , , pattern]) => pattern.test(raw));
  const hosts = matches.filter(([key]) => HOSTS.has(key));
  // Exactly one host named: it outranks model brands ("claude via openrouter").
  // Two hosts, or several brands and no host: ambiguous, so no link.
  if (hosts.length === 1) return hosts[0];
  return matches.length === 1 && hosts.length === 0 ? matches[0] : undefined;
}

export function turnErrorInfo(raw, explicitCode, context = {}) {
  try {
    // Cap what the regexes see: error text is model-supplied and unbounded,
    // and a few patterns have bounded-but-real backtracking. Same cap as
    // the Python classifier so both sides read the same prefix.
    const text = (
      typeof raw === "object" && raw !== null
        ? JSON.stringify(raw)
        : String(raw ?? "")
    ).slice(0, MAX_CLASSIFY_CHARS);
    const inferred =
      compiled.find((rule) => rule.test.test(text))?.code || "gateway";
    // Older servers publish broad gateway/provider codes. Refine those from
    // the saved text too, so historical and live errors get the same remedy.
    const code =
      !explicitCode || ["gateway", "provider"].includes(explicitCode)
        ? inferred === "gateway"
          ? explicitCode || inferred
          : inferred
        : explicitCode;
    const rule = Object.hasOwn(byCode, code) ? byCode[code] : byCode.internal;
    const provider = rule.status ? providerFor(text, context) : undefined;
    // A status link supplements the cause-specific guidance; it must not
    // turn a timeout or connection failure into an asserted provider outage.
    const providerCopy = provider
      ? {
          "service-unavailable": {
            headline: `${provider[1]} could not complete this request`,
            hint: "Try again shortly, or choose another available model.",
          },
          timeout: {
            headline: `${provider[1]} did not respond in time`,
            hint: "Try again, split a large request into smaller parts, or choose another available model.",
          },
          connection: {
            headline: `Jarvis could not connect to ${provider[1]}`,
            hint: "Try again or choose another available model. If this continues, ask your administrator to check the connection.",
          },
        }
      : {};
    const copy = Object.hasOwn(providerCopy, code) ? providerCopy[code] : rule;
    return {
      code,
      headline: copy.headline,
      hint: copy.hint,
      retryable: rule.retryable,
      statusUrl: provider?.[2] || "",
      statusLabel: provider ? `Check ${provider[1]} status` : "",
    };
  } catch {
    return {
      code: "internal",
      headline: byCode.internal.headline,
      hint: byCode.internal.hint,
      retryable: true,
      statusUrl: "",
      statusLabel: "",
    };
  }
}
