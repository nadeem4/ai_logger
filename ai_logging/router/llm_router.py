import logging
from typing import Any, Dict, List, Optional

from ..config.settings import Settings, get_settings
from ..providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Static defaults declared in settings.py for the OpenAI provider. If the
# configured provider is anthropic and the user has not overridden these
# settings (i.e. they still equal the OpenAI defaults), the router swaps in
# the Anthropic tier defaults instead. Comparing against the known OpenAI
# defaults is how we detect "not overridden" without adding provider-aware
# fields to Settings.
_DEFAULT_FAST_MODEL = "gpt-4o-mini"
_DEFAULT_CAPABLE_MODEL = "gpt-4o"
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

        if self.fast is None and self.capable is None:
            self._warn_no_providers()

    def _build_providers_from_settings(self):
        """Builds (fast, capable) providers from settings when the caller
        did not inject either one. Returns (None, None) if the configured
        provider's API key is not set."""
        provider = self.settings.ai_logging_provider

        fast_model = self.settings.ai_logging_fast_model
        capable_model = self.settings.ai_logging_capable_model

        if provider == "anthropic":
            if not self.settings.anthropic_api_key:
                return None, None
            # Settings keep the static OpenAI defaults; substitute the
            # Anthropic tier defaults unless the user overrode them.
            if fast_model == _DEFAULT_FAST_MODEL:
                fast_model = _ANTHROPIC_FAST_MODEL
            if capable_model == _DEFAULT_CAPABLE_MODEL:
                capable_model = _ANTHROPIC_CAPABLE_MODEL
            from ..providers.anthropic_provider import AnthropicProvider

            fast = AnthropicProvider(model=fast_model, api_key=self.settings.anthropic_api_key)
            capable = AnthropicProvider(model=capable_model, api_key=self.settings.anthropic_api_key)
            return fast, capable

        # Default: openai
        if not self.settings.openai_api_key:
            return None, None
        from ..providers.openai_provider import OpenAIProvider

        fast = OpenAIProvider(model=fast_model, api_key=self.settings.openai_api_key)
        capable = OpenAIProvider(model=capable_model, api_key=self.settings.openai_api_key)
        return fast, capable

    def _warn_no_providers(self) -> None:
        if not self._warned_no_providers:
            logger.warning(
                "No LLM providers available (no API key configured for provider '%s'). "
                "route_prompt() will return None.",
                self.settings.ai_logging_provider,
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

        threshold = logging.getLevelName(self.settings.ai_logging_capable_severity_threshold.upper())

        if highest_severity >= threshold and self.capable is not None:
            provider = self.capable
        elif self.fast is not None:
            provider = self.fast
        else:
            provider = self.capable

        return provider.complete(prompt)
