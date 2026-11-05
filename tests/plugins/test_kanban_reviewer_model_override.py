"""tests verifying that per-task model overrides do not leak into reviewer runs (#149355)."""

from pathlib import Path
from types import SimpleNamespace

from gateway.session_contract import SessionActor
from gateway.session_kanban import build_kanban_policy
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


def test_reviewer_run_ignores_implementer_model_override(tmp_path, monkeypatch):
    """reviewer run uses reviewer profile model, not task implementer model override."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    monkeypatch.delenv("HERMES_DELEGATED_CHILD", raising=False)

    coder_profile = home / "profiles" / "coder"
    reviewer_profile = home / "profiles" / "reviewer"
    coder_profile.mkdir(parents=True)
    reviewer_profile.mkdir(parents=True)
    (coder_profile / "config.yaml").write_text("{}\n")
    (reviewer_profile / "config.yaml").write_text("{}\n")

    monkeypatch.setattr(
        "hermes_cli.profiles.resolve_profile_env",
        lambda name: str(coder_profile if name == "coder" else reviewer_profile),
    )

    kb.init_db()
    conn = kbc.connect()

    workspace = tmp_path / "ws"
    workspace.mkdir()

    tid = kb.create_task(
        conn,
        title="implement feature",
        assignee="coder",
        workspace_kind="dir",
        workspace_path=str(workspace),
        model_override="claude-opus-override",
        provider_override="anthropic",
        reasoning_effort="high",
    )

    # 1. implementer claim: should use the task model override
    task_coder = kb.claim_task(conn, tid)
    assert task_coder is not None

    coder_actor = SessionActor("coder", str(coder_profile), frozenset({"session:create"}), "transport")
    coder_conn = SimpleNamespace(
        authority=SimpleNamespace(profile_id=str(coder_profile)),
        actor=coder_actor,
        native_owner=True,
    )
    coder_params = {
        "board": "default",
        "task_id": tid,
        "run_id": task_coder.current_run_id,
        "claim_lock": task_coder.claim_lock,
    }
    coder_config = {
        "model": {"default": "coder-default-model", "provider": "custom"},
        "platform_toolsets": {"cli": ["terminal"]},
    }

    coder_policy, _ = build_kanban_policy(coder_conn, coder_params, coder_config)
    assert coder_policy.model == "claude-opus-override"
    assert coder_policy.provider == "anthropic"
    assert coder_policy.reasoning_config == {"enabled": True, "effort": "high"}

    # 2. request review: task moves to review status and reassigns to reviewer
    ok = kb.request_review(
        conn,
        tid,
        reviewer="reviewer",
        expected_run_id=task_coder.current_run_id,
        summary="ready for review",
    )
    assert ok is True

    # 3. reviewer claims review task: must use reviewer profile model, not implementer override
    task_reviewer = kb.claim_review_task(conn, tid)
    assert task_reviewer is not None
    assert task_reviewer.assignee == "reviewer"

    reviewer_actor = SessionActor("reviewer", str(reviewer_profile), frozenset({"session:create"}), "transport")
    reviewer_conn = SimpleNamespace(
        authority=SimpleNamespace(profile_id=str(reviewer_profile)),
        actor=reviewer_actor,
        native_owner=True,
    )
    reviewer_params = {
        "board": "default",
        "task_id": tid,
        "run_id": task_reviewer.current_run_id,
        "claim_lock": task_reviewer.claim_lock,
    }
    reviewer_config = {
        "model": {"default": "reviewer-audit-model", "provider": "custom"},
        "platform_toolsets": {"cli": ["terminal"]},
    }

    reviewer_policy, _ = build_kanban_policy(reviewer_conn, reviewer_params, reviewer_config)
    assert reviewer_policy.model == "reviewer-audit-model"
    assert reviewer_policy.provider == "custom"
    assert reviewer_policy.reasoning_config is None

    # 4. reviewer requests changes: task goes back to implementer
    ok, _ = kb.request_changes(
        conn,
        tid,
        reason="please address review comments",
        expected_run_id=task_reviewer.current_run_id,
    )
    assert ok is True

    # 5. implementer re-claims task: implementer override applies again
    task_coder_round2 = kb.claim_task(conn, tid)
    assert task_coder_round2 is not None
    assert task_coder_round2.assignee == "coder"

    coder_params_round2 = {
        "board": "default",
        "task_id": tid,
        "run_id": task_coder_round2.current_run_id,
        "claim_lock": task_coder_round2.claim_lock,
    }

    coder_policy_round2, _ = build_kanban_policy(coder_conn, coder_params_round2, coder_config)
    assert coder_policy_round2.model == "claude-opus-override"
    assert coder_policy_round2.provider == "anthropic"
    assert coder_policy_round2.reasoning_config == {"enabled": True, "effort": "high"}

    conn.close()
