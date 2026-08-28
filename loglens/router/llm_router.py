import logging
from typing import Any, Dict, List, Optional

from ..config.settings import Settings, get_settings
from ..providers.base import LLMProvider, ProviderError

logger = logging.getLogger(__name__)

# Settings keeps loglens_fast_model / loglens_capable_model as static
# OpenAI defaults ("gpt-4o-mini" / "gpt-4o") per the brief. When the
# configured provider is anthropic, the router substitutes these Anthropic
# tier defaults instead — but only for fields the user did not explicitly
# set. We detect "explicitly set" via pydantic-settings' `model_fields_set`,
# which records every field that was supplied (env var, .env, or
# constructor kwarg) even when the supplied value equals the field default.
# That is what lets us tell "user left it alone" apart from "user set it to
# exactly gpt-4o-mini on purpose" — a literal-value comparison cannot.
_ANTHROPIC_FAST_MODEL = "claude-3-5-haiku-latest"
_ANTHROPIC_CAPABLE_MODEL = "claude-sonnet-4-5"


class LLMRouter:
    """
    Routes a prompt to a fast or capable LLM provider based on the highest
    log severity present in the batch that produced the prompt.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        fast: Optional[LLMProvider] = None,
        capable: Optional[LLMProvider] = None,
    ):
        self.settings = settings or get_settings()
        self._warned_no_providers = False

        if fast is None and capable is None:
            fast, capable = self._build_providers_from_settings()

        self.fast = fast
        self.capable = capable
        # Note: the "no providers available" warning is emitted lazily, the
        # first time route_prompt() is called and finds nothing to route
        # to — not here in __init__ — so a router that's constructed but
        # never used stays silent, and "warn once" means once per instance
        # regardless of how many route_prompt() calls follow.

    def _build_providers_from_settings(self):
        """Builds (fast, capable) providers from settings when the caller
        did not inject either one. Returns (None, None) if the configured
        provider's API key is not set, or if the provider cannot be built
        (e.g. its optional SDK is not installed).

        A logging misconfiguration must never take down the host
        application at startup, so a ProviderError here degrades to "no
        providers" -- exactly like the missing-key path -- with a warning,
        rather than propagating out of AIHandler.__init__()."""
        provider = self.settings.loglens_provider

        fast_model = self.settings.loglens_fast_model
        capable_model = self.settings.loglens_capable_model

        if provider == "anthropic":
            if not self.settings.anthropic_api_key:
                return None, None
            # Substitute the Anthropic tier defaults only for fields the
            # user did not explicitly set (see module docstring above).
            fields_set = self.settings.model_fields_set
            if "loglens_fast_model" not in fields_set:
                fast_model = _ANTHROPIC_FAST_MODEL
            if "loglens_capable_model" not in fields_set:
                capable_model = _ANTHROPIC_CAPABLE_MODEL
            try:
                from ..providers.anthropic_provider import AnthropicProvider

                fast = AnthropicProvider(model=fast_model, api_key=self.settings.anthropic_api_key)
                capable = AnthropicProvider(model=capable_model, api_key=self.settings.anthropic_api_key)
            except ProviderError as e:
                self._warn_provider_unavailable(provider, e)
                return None, None
            return fast, capable

        # Default: openai
        if not self.settings.openai_api_key:
            return None, None
        try:
            from ..providers.openai_provider import OpenAIProvider

            fast = OpenAIProvider(model=fast_model, api_key=self.settings.openai_api_key)
            capable = OpenAIProvider(model=capable_model, api_key=self.settings.openai_api_key)
        except ProviderError as e:
            self._warn_provider_unavailable(provider, e)
            return None, None
        return fast, capable

    def _warn_provider_unavailable(self, provider: str, error: Exception) -> None:
        logger.warning(
            "Could not build LLM provider '%s': %s. AI logging is disabled "
            "(route_prompt() will return None).",
            provider,
            error,
        )

    def _warn_no_providers(self) -> None:
        if not self._warned_no_providers:
            logger.warning(
                "No LLM providers available (no API key configured for provider '%s'). "
                "route_prompt() will return None.",
                self.settings.loglens_provider,
            )
            self._warned_no_providers = True

    def route_prompt(self, prompt: str, log_records: List[Dict[str, Any]]) -> Optional[str]:
        """
        Routes a prompt to the capable or fast provider based on the highest
        severity in log_records, and returns the provider's response.

        Returns None if no provider is available. Lets ProviderError
        propagate so AIHandler's retry logic can act on it.
        """
        if self.fast is None and self.capable is None:
            self._warn_no_providers()
            return None

        highest_severity = max(
            (r.get("levelno", 0) for r in log_records if isinstance(r.get("levelno", 0), int)),
            default=logging.INFO,
        )

        threshold = logging.getLevelName(self.settings.loglens_capable_severity_threshold.upper())

        if highest_severity >= threshold and self.capable is not None:
            provider = self.capable
        elif self.fast is not None:
            provider = self.fast
        else:
            provider = self.capable

        return provider.complete(prompt)
