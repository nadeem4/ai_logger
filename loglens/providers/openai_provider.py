from typing import Optional
from .base import LLMProvider, ProviderError


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str, api_key: str, client: Optional[object] = None):
        self.model = model
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ProviderError("openai SDK not installed — pip install 'openai>=1'") from e
            client = OpenAI(api_key=api_key)
        self._client = client

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
