from typing import Any, Protocol

from .base import LLMProvider, ProviderError


class _AnthropicClientLike(Protocol):
    """Structural type for the piece of the anthropic SDK client we actually
    use. Declared here (rather than importing `anthropic.Anthropic` for the
    annotation) so the SDK stays a lazy, function-scoped import -- `import
    logscribe` must succeed without `anthropic` installed. `messages` is typed
    `Any` deliberately: the real response is a large block-type union (text,
    tool-use, thinking, ...) we don't need to model -- `complete()` already
    wraps any unexpected shape (e.g. a non-text first block) in a
    ProviderError via its broad `except Exception`.
    """

    @property
    def messages(self) -> Any: ...


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        client: _AnthropicClientLike | None = None,
        max_tokens: int = 1024,
    ):
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise ProviderError("anthropic SDK not installed — pip install anthropic") from e
            client = Anthropic(api_key=api_key)
        # Explicit annotation: without it, mypy infers self._client's type
        # from the narrower concrete `Anthropic` assigned just above, which
        # defeats the point of the Protocol (its `messages -> Any` is what
        # keeps complete() from being checked against the real SDK's full
        # response-block union).
        self._client: _AnthropicClientLike = client

    def complete(self, prompt: str) -> str:
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Anthropic call failed: {e}") from e
