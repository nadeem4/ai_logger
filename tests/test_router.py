import logging
from ai_logging.router.llm_router import LLMRouter

class Fake:
    def __init__(self, name): self.model = name; self.prompts = []
    def complete(self, p): self.prompts.append(p); return f"resp-{self.model}"

def test_error_batch_routes_to_capable():
    r = LLMRouter(fast=Fake("fast"), capable=Fake("capable"))
    out = r.route_prompt("p", [{"levelno": logging.ERROR}])
    assert out == "resp-capable"

def test_info_batch_routes_to_fast():
    r = LLMRouter(fast=Fake("fast"), capable=Fake("capable"))
    assert r.route_prompt("p", [{"levelno": logging.INFO}]) == "resp-fast"

def test_no_providers_returns_none():
    r = LLMRouter(fast=None, capable=None)
    assert r.route_prompt("p", [{"levelno": logging.INFO}]) is None

def test_provider_error_propagates_for_handler_retry():
    from ai_logging.providers.base import ProviderError
    class Boom:
        model = "x"
        def complete(self, p): raise ProviderError("down")
    r = LLMRouter(fast=Boom(), capable=Boom())
    import pytest
    with pytest.raises(ProviderError):
        r.route_prompt("p", [{"levelno": logging.INFO}])
