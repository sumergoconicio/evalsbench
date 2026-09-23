"""
Direct cloud provider routing for EvalsBench.

Maps provider-prefixed model strings (``google/*``, ``deepseek/*``,
``anthropic/*``, ``openai/*``, ``openrouter/*``) onto Inspect AI's
native vendor execution paths, sourcing API keys directly from
``~/chai/.env`` (the secrets single source of truth). Local model
aliases (anything without a recognized cloud prefix) fall through to
the OpenAI-compatible endpoint path unchanged.

Design contract (PRD §6.3): no LiteLLM proxy wrappers — cloud models
ride Inspect AI's built-in providers, so the runner only needs to (a)
forward the correct provider environment variables into the inspect
subprocess and (b) stop forcing the ``openai/`` model prefix.
"""

import os
from typing import Dict, List, Optional, Tuple

from .config import load_chai_env

#: Provider prefix → canonical credential environment variable names.
#: The first name is the primary key; any additional names are
#: alternates Inspect AI (or the vendor SDK) also accepts.
CLOUD_PROVIDERS: Dict[str, List[str]] = {
    "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
}

#: Endpoint URL fragments that imply a cloud provider even when the
#: model string itself carries no prefix (e.g. a raw model id pointed
#: at the OpenRouter gateway).
_CLOUD_ENDPOINT_HINTS: Tuple[str, ...] = (
    "openrouter.ai",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.deepseek.com",
)


def _detect_provider(model_name: str, endpoint_url: Optional[str]) -> Optional[str]:
    """Infer the provider id from the model prefix or endpoint URL.

    Args:
        model_name: Raw model string (e.g. ``google/gemini-2.5-flash``).
        endpoint_url: Optional endpoint base URL hint.

    Returns:
        Provider id (``"google"``, ``"deepseek"``, ...) or ``None``
        when the model should route to the local OpenAI-compatible
        path.
    """
    model_name = (model_name or "").strip()
    if "/" in model_name:
        prefix = model_name.split("/", 1)[0].lower()
        if prefix in CLOUD_PROVIDERS:
            return prefix

    endpoint_url = (endpoint_url or "").lower()
    for hint in _CLOUD_ENDPOINT_HINTS:
        if hint in endpoint_url:
            # Endpoint implies a vendor gateway; map by fragment.
            if "openrouter" in hint:
                return "openrouter"
            if "anthropic" in hint:
                return "anthropic"
            if "google" in hint:
                return "google"
            if "deepseek" in hint:
                return "deepseek"
            return "openai"
    return None


def resolve_model_and_env(
    model_name: str,
    endpoint_url: Optional[str] = None,
) -> Tuple[str, str, bool, Dict[str, str]]:
    """Resolve a model string into a provider routing decision.

    For cloud providers, credentials are pulled (in order of
    precedence) from ``~/chai/.env`` and then the ambient process
    environment, and returned as an ``env_overrides`` dict the runner
    merges into the inspect subprocess environment. Missing keys are
    reported once to stderr under the Missing Secrets Protocol — the
    function never fails silently and never invents dummy values.

    Args:
        model_name: Raw model string (e.g. ``google/gemini-2.5-flash``
            or a local alias like ``master-lite``).
        endpoint_url: Optional endpoint hint for prefix-less cloud
            models routed through a vendor gateway.

    Returns:
        Tuple of:

        * ``resolved_model`` — the model string to hand to Inspect AI
          (unchanged for cloud; the caller adds the ``openai/`` shim
          for local models).
        * ``provider`` — ``"local"`` or the cloud provider id.
        * ``is_cloud`` — ``True`` when the model routes to a vendor.
        * ``env_overrides`` — provider credential variables to inject
          into the subprocess environment (empty for local models).
    """
    model_name = (model_name or "").strip()
    provider = _detect_provider(model_name, endpoint_url)

    if provider is None:
        return model_name, "local", False, {}

    chai_env = load_chai_env()
    env_overrides: Dict[str, str] = {}
    missing: List[str] = []

    for key_name in CLOUD_PROVIDERS[provider]:
        value = chai_env.get(key_name) or os.environ.get(key_name) or ""
        if value:
            env_overrides[key_name] = value
        else:
            missing.append(key_name)

    if missing:
        # Missing Secrets Protocol: surface the gap explicitly rather
        # than failing later with an opaque vendor auth error.
        import sys

        print(
            f"Warning: router.py — no {' or '.join(missing)} found in "
            f"~/chai/.env or environment for provider '{provider}'. "
            f"Add the key to ~/chai/.env before running cloud evals.",
            file=sys.stderr,
        )

    return model_name, provider, True, env_overrides


def is_cloud_model(model_name: str, endpoint_url: Optional[str] = None) -> bool:
    """Boolean convenience wrapper around :func:`resolve_model_and_env`."""
    return resolve_model_and_env(model_name, endpoint_url)[2]
