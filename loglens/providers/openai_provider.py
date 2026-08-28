from typing import Any, Optional, Protocol

from .base import LLMProvider, ProviderError


class _OpenAIClientLike(Protocol):
    """Structural type for the piece of the openai SDK client we actually
    use. Declared here (rather than importing `openai.OpenAI` for the
    annotation) so the SDK stays a lazy, function-scoped import -- `import
    loglens` must succeed without `openai` installed. `chat` is typed `Any`
    deliberately: the full response shape isn't our concern to model, and
    doing so accurately would require importing the real SDK types anyway.
    """

    @property
    def chat(self) -> Any: ...


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str, api_key: str, client: Optional[_OpenAIClientLike] = None):
        self.model = model
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ProviderError("openai SDK not installed — pip install 'openai>=1'") from e
            client = OpenAI(api_key=api_key)
        # Explicit annotation: without it, mypy infers self._client's type
        # from the narrower concrete `OpenAI` assigned just above, tying
        # complete() to the real SDK's response types instead of the
        # Protocol's deliberately loose `chat -> Any`.
        self._client: _OpenAIClientLike = client

    def complete(self, prompt: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or ""
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"OpenAI call failed: {e}") from e
