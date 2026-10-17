import asyncio
import contextlib
from types import SimpleNamespace
import pytest

from hermes_cli.web_routers import models as _rt_models
from hermes_cli.web_models import ModelAssignment


@pytest.mark.asyncio
async def test_auxiliary_assignment_selection_guard_blocks_without_confirm(monkeypatch):
    warning = SimpleNamespace(message="data logging warning")
    monkeypatch.setattr(
        "hermes_cli.model_selection_guards.combined_selection_warning",
        lambda *a, **k: warning,
    )
    monkeypatch.setattr(_rt_models, "_dashboard_code_skew_guard", lambda: None)

    body = ModelAssignment(
        scope="auxiliary",
        task="vision",
        provider="nous",
        model="hermes-4-contributor",
        confirm_expensive_model=False,
    )
    res = await _rt_models.set_model_assignment(body)
    assert res["ok"] is False
    assert res["confirm_required"] is True
    assert res["confirm_message"] == "data logging warning"


@pytest.mark.asyncio
async def test_auxiliary_assignment_selection_guard_proceeds_with_confirm(monkeypatch):
    warning = SimpleNamespace(message="data logging warning")
    monkeypatch.setattr(
        "hermes_cli.model_selection_guards.combined_selection_warning",
        lambda *a, **k: warning,
    )
    monkeypatch.setattr(_rt_models, "_dashboard_code_skew_guard", lambda: None)
    monkeypatch.setattr(_rt_models, "_profile_scope", lambda profile: contextlib.nullcontext())
    monkeypatch.setattr(
        _rt_models,
        "_apply_model_assignment_sync",
        lambda *a, **k: {"ok": True, "scope": "auxiliary", "task": "vision"},
    )

    body = ModelAssignment(
        scope="auxiliary",
        task="vision",
        provider="nous",
        model="hermes-4-contributor",
        confirm_expensive_model=True,
    )
    res = await _rt_models.set_model_assignment(body)
    assert res["ok"] is True
    assert res["scope"] == "auxiliary"


@pytest.mark.asyncio
async def test_auxiliary_reset_bypasses_selection_guards(monkeypatch):
    # reset all to main sends main model credentials and model name, but resets slots to auto.
    # selection guard must not block reset (#140545).
    warning = SimpleNamespace(message="expensive tier warning")
    monkeypatch.setattr(
        "hermes_cli.model_selection_guards.combined_selection_warning",
        lambda *a, **k: warning,
    )
    monkeypatch.setattr(_rt_models, "_dashboard_code_skew_guard", lambda: None)
    monkeypatch.setattr(_rt_models, "_profile_scope", lambda profile: contextlib.nullcontext())
    applied = []
    monkeypatch.setattr(
        _rt_models,
        "_apply_model_assignment_sync",
        lambda *a, **k: applied.append(a) or {"ok": True, "scope": "auxiliary", "reset": True},
    )

    body = ModelAssignment(
        scope="auxiliary",
        task="__reset__",
        provider="nous",
        model="hermes-4-contributor",
        confirm_expensive_model=False,
    )
    res = await _rt_models.set_model_assignment(body)
    assert res["ok"] is True
    assert res["reset"] is True
    assert len(applied) == 1
