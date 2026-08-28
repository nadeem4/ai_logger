from abc import ABC, abstractmethod

class ProviderError(Exception):
    """Raised when an LLM provider call fails."""

class LLMProvider(ABC):
    model: str
    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send prompt, return the model's text response."""
