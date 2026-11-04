"""execution middleware preserves downstream exception chains."""

from types import SimpleNamespace

import pytest

from agent.error_classifier import _extract_error_body, _extract_status_code
from hermes_cli import middleware


@pytest.mark.parametrize("kind", ["llm_execution", "tool_execution"])
@pytest.mark.parametrize("layers", [0, 1, 2])
@pytest.mark.parametrize("active_exception", [False, True])
def test_downstream_implicit_context_survives_middleware(monkeypatch, kind, layers, active_exception):
    def passthrough(next_call, **kwargs):
        return next_call()

    manager = SimpleNamespace(_middleware={kind: [passthrough] * layers})
    monkeypatch.setattr("hermes_cli.plugins._delivery_manager", lambda: manager)

    class ProviderError(Exception):
        status_code = 429
        body = {"error": {"message": "rate limited"}}

    def terminal(_payload):
        try:
            raise ProviderError("rate limited")
        except ProviderError:
            raise RuntimeError("stream failed")

    def run():
        with pytest.raises(RuntimeError) as caught:
            if kind == "llm_execution":
                middleware.run_llm_execution_middleware({}, terminal)
            else:
                middleware.run_tool_execution_middleware("tool", {}, terminal)
        error = caught.value
        assert isinstance(error.__context__, ProviderError)
        assert _extract_status_code(error) == 429
        assert _extract_error_body(error) == ProviderError.body

    if active_exception:
        try:
            raise ValueError("caller is handling an exception")
        except ValueError:
            run()
    else:
        run()


@pytest.mark.parametrize("suppress", [False, True])
def test_downstream_explicit_cause_and_suppression_survive(monkeypatch, suppress):
    def passthrough(next_call, **kwargs):
        return next_call()

    manager = SimpleNamespace(_middleware={"llm_execution": [passthrough, passthrough]})
    monkeypatch.setattr("hermes_cli.plugins._delivery_manager", lambda: manager)
    cause = ValueError("cause")

    def terminal(_request):
        if suppress:
            raise RuntimeError("failure") from None
        raise RuntimeError("failure") from cause

    with pytest.raises(RuntimeError) as caught:
        middleware.run_llm_execution_middleware({}, terminal)
    assert caught.value.__cause__ is (None if suppress else cause)
    assert caught.value.__suppress_context__ is True
