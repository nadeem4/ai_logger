from typing import Optional
from .base import LLMProvider, ProviderError

class AnthropicProvider(LLMProvider):
    def __init__(self, model: str, api_key: str, client: Optional[object] = None, max_tokens: int = 1024):
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise ProviderError("anthropic SDK not installed — pip install anthropic") from e
            client = Anthropic(api_key=api_key)
        self._client = client

    def complete(self, prompt: str) -> str:
        try:
            resp = self._client.messages.create(
                model=self.model, max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Anthropic call failed: {e}") from e
