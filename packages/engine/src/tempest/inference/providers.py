"""The provider registry (P1) — **a provider is data, not code** (L18, ADR-0037).

The master prompt requires 12+ providers and that "adding a provider must not touch feature
code". Both fall out of one observation: **two wire protocols cover the entire market.**
Anthropic speaks its own Messages API; everyone else — OpenAI, Azure, Google's compatibility
endpoint, groq, Mistral, DeepSeek, OpenRouter, Together, Perplexity, xAI, Fireworks, Cerebras,
and every local runner (Ollama, LM Studio, llama.cpp) — speaks OpenAI Chat Completions.

So breadth costs **two adapters and N rows in a table**, not N integrations. Adding a provider
is appending a `Provider(...)` below; a test asserts that a provider invented at runtime works
end to end, which is what makes "must not touch feature code" a checked claim rather than a
slogan.

**Keys never live here.** Each row names the environment variable its key arrives in; the value
comes from the OS keychain via the host's per-spawn env injection (L18 — never plaintext, never
synced, never in this file).

**Local providers need no key and work with the network unplugged**, which is how L23's
air-gapped story is concrete rather than aspirational: with Ollama or llama.cpp configured,
every generative feature keeps working offline.
"""

from dataclasses import dataclass

#: The Anthropic Messages API.
WIRE_ANTHROPIC = "anthropic"
#: OpenAI Chat Completions — spoken by every OpenAI-compatible endpoint.
WIRE_OPENAI = "openai"
WIRES = (WIRE_ANTHROPIC, WIRE_OPENAI)

#: Per-provider base-URL override, e.g. TEMPEST_MODEL_BASE_URL_AZURE_OPENAI. Azure and the
#: self-hosted runners are per-deployment by nature, so the row carries a sensible default and
#: the environment carries the truth.
BASE_URL_ENV_PREFIX = "TEMPEST_MODEL_BASE_URL_"


@dataclass(frozen=True)
class Provider:
    """One endpoint Tempest can reach. Every field is data; none of it is behaviour."""

    id: str
    label: str
    wire: str
    base_url: str
    #: Environment variable carrying the API key. Empty for local runners.
    env_var: str
    #: A starting suggestion the user overrides in Settings. **Not a claim that this model id
    #: is current** — model names change faster than any registry, so the client surfaces the
    #: provider's own error verbatim when a model is rejected, rather than pretending to know.
    default_model: str | None
    #: Runs on the user's machine: no key, and it works with the network unplugged (L23).
    local: bool = False
    #: Static model-spec metadata, ADOPTED from upstream LibreChat's `defaultModels` tables
    #: (provider/src/config.ts at the vendored commit) for the providers upstream declares
    #: statically — refreshed at every upstream merge (L27), never invented here. Providers
    #: upstream serves by LIVE fetch keep an empty tuple and are discovered the same way:
    #: the catalog route probes `{base_url}/models` — always for local runners (loopback,
    #: keyless), and for remote providers only when their key is configured, which is the
    #: same user-sanctioned BYOK egress surface `verify_key` already uses (L10, ADR-0024).
    models: tuple[str, ...] = ()
    #: The provider's DOCUMENTED context window in tokens, when one number holds across its
    #: models — the context gauge's denominator (LC21). `None` means unknown, and unknown
    #: renders as an indeterminate gauge, never an invented percentage: a wrong maximum is
    #: worse than no maximum.
    context_window: int | None = None

    @property
    def needs_key(self) -> bool:
        return not self.local and bool(self.env_var)

    def base_url_env(self) -> str:
        """The variable that overrides `base_url` for this provider."""
        return BASE_URL_ENV_PREFIX + self.id.upper().replace("-", "_")


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="anthropic",
        label="Anthropic",
        wire=WIRE_ANTHROPIC,
        base_url="https://api.anthropic.com",
        env_var="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-5",
        # docs.anthropic.com: 200k across the current model family.
        context_window=200_000,
        models=(
            # Upstream sharedAnthropicModels at the vendored commit, dated duplicate
            # aliases collapsed onto their canonical ids — refreshed at upstream merges.
            "claude-fable-5",
            "claude-opus-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-sonnet-5",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-opus-4-1",
            "claude-opus-4-5",
            "claude-sonnet-4-0",
            "claude-opus-4-0",
            "claude-3-7-sonnet-latest",
            "claude-3-5-haiku-20241022",
            "claude-3-5-sonnet-latest",
        ),
    ),
    Provider(
        id="openai",
        label="OpenAI",
        wire=WIRE_OPENAI,
        base_url="https://api.openai.com/v1",
        env_var="OPENAI_API_KEY",
        default_model=None,
        models=(
            # Upstream sharedOpenAIModels at the vendored commit, the legacy instruct/vision
            # tail dropped — refreshed at upstream merges.
            "gpt-5.6",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-5.5",
            "gpt-5.5-pro",
            "chat-latest",
            "gpt-5.4",
            "gpt-5.4-pro",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.3-codex",
            "gpt-5.2",
            "gpt-5.1",
            "gpt-5.1-codex",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
        ),
    ),
    Provider(
        id="azure-openai",
        label="Azure OpenAI",
        wire=WIRE_OPENAI,
        # Per-deployment; the row is a placeholder and the env var carries the real endpoint.
        base_url="https://YOUR-RESOURCE.openai.azure.com/openai/v1",
        env_var="AZURE_OPENAI_API_KEY",
        default_model=None,
    ),
    Provider(
        id="google-gemini",
        label="Google Gemini",
        wire=WIRE_OPENAI,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        env_var="GOOGLE_API_KEY",
        default_model=None,
        models=(
            # Upstream defaultModels[google] at the vendored commit — refreshed at
            # upstream merges.
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-pro-preview",
            "gemini-3-pro-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ),
    ),
    Provider(
        id="groq",
        label="Groq",
        wire=WIRE_OPENAI,
        base_url="https://api.groq.com/openai/v1",
        env_var="GROQ_API_KEY",
        default_model=None,
    ),
    Provider(
        id="mistral",
        label="Mistral",
        wire=WIRE_OPENAI,
        base_url="https://api.mistral.ai/v1",
        env_var="MISTRAL_API_KEY",
        default_model=None,
    ),
    Provider(
        id="deepseek",
        label="DeepSeek",
        wire=WIRE_OPENAI,
        base_url="https://api.deepseek.com/v1",
        env_var="DEEPSEEK_API_KEY",
        default_model=None,
    ),
    Provider(
        id="openrouter",
        label="OpenRouter",
        wire=WIRE_OPENAI,
        base_url="https://openrouter.ai/api/v1",
        env_var="OPENROUTER_API_KEY",
        default_model=None,
    ),
    Provider(
        id="together",
        label="Together AI",
        wire=WIRE_OPENAI,
        base_url="https://api.together.xyz/v1",
        env_var="TOGETHER_API_KEY",
        default_model=None,
    ),
    Provider(
        id="perplexity",
        label="Perplexity",
        wire=WIRE_OPENAI,
        base_url="https://api.perplexity.ai",
        env_var="PERPLEXITY_API_KEY",
        default_model=None,
    ),
    Provider(
        id="xai",
        label="xAI",
        wire=WIRE_OPENAI,
        base_url="https://api.x.ai/v1",
        env_var="XAI_API_KEY",
        default_model=None,
    ),
    Provider(
        id="fireworks",
        label="Fireworks AI",
        wire=WIRE_OPENAI,
        base_url="https://api.fireworks.ai/inference/v1",
        env_var="FIREWORKS_API_KEY",
        default_model=None,
    ),
    Provider(
        id="cerebras",
        label="Cerebras",
        wire=WIRE_OPENAI,
        base_url="https://api.cerebras.ai/v1",
        env_var="CEREBRAS_API_KEY",
        default_model=None,
    ),
    # --- local runners: no key, and they keep every generative feature alive offline (L23) ---
    Provider(
        id="ollama",
        label="Ollama (local)",
        wire=WIRE_OPENAI,
        base_url="http://127.0.0.1:11434/v1",
        env_var="",
        default_model=None,
        local=True,
    ),
    Provider(
        id="lmstudio",
        label="LM Studio (local)",
        wire=WIRE_OPENAI,
        base_url="http://127.0.0.1:1234/v1",
        env_var="",
        default_model=None,
        local=True,
    ),
    Provider(
        id="llamacpp",
        label="llama.cpp server (local)",
        wire=WIRE_OPENAI,
        base_url="http://127.0.0.1:8080/v1",
        env_var="",
        default_model=None,
        local=True,
    ),
)


class UnknownProvider(KeyError):
    """The configured provider id is not in the registry. The message lists what is."""


def ids() -> list[str]:
    return [p.id for p in PROVIDERS]


def get(provider_id: str) -> Provider:
    for provider in PROVIDERS:
        if provider.id == provider_id:
            return provider
    raise UnknownProvider(
        f"unknown provider {provider_id!r} — configured providers are: {', '.join(ids())}"
    )


def local_ids() -> list[str]:
    """Providers that need no key and work with the network unplugged (L23)."""
    return [p.id for p in PROVIDERS if p.local]
