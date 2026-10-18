"""`hermes update` refuses a target that predates the gateway runtime once a state.db holds ledger rows.

Downgrading is unsupported (#106742, jquesnelle item 6): the older release cannot delete or prune
the sessions with runtime history, so the move is refused before the tree changes and the message
names the pre-update snapshot that predates the cutover.
"""
import sqlite3
import subprocess
from contextlib import closing
from types import SimpleNamespace

import pytest

import hermes_state_runtime as rt
from hermes_cli import update_downgrade_guard as guard
from hermes_state import SessionDB


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "hermes_state_common.py").write_text("SCHEMA_SQL = 'CREATE TABLE IF NOT EXISTS sessions (id TEXT)'\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "release before the cutover")
    _git(root, "checkout", "-b", "maintenance")
    (root / "notes.txt").write_text("maintenance fix\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "side maintenance release")
    _git(root, "tag", "old-release")
    _git(root, "checkout", "main")
    (root / "hermes_state_common.py").write_text(
        "SCHEMA_SQL = '''CREATE TABLE IF NOT EXISTS session_admissions (seq INTEGER)'''\n")
    _git(root, "commit", "-am", "gateway runtime")
    return root


def _ledgered_store(home):
    home.mkdir(parents=True, exist_ok=True)
    with closing(SessionDB(home / "state.db")) as db:
        epoch = rt.begin_runtime_epoch(db, instance_id="owner")
        db.create_session("s", source="cli")
        rt.admit_session_input(db, epoch=epoch, principal_id="p", session_id="s", request_id="r",
                               payload={"text": "x"})


def _pre_cutover_snapshot(home, snap_id):
    snap = home / "state-snapshots" / snap_id
    snap.mkdir(parents=True)
    with closing(sqlite3.connect(snap / "state.db")) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")


def test_a_pre_runtime_target_is_refused_before_the_move_with_the_snapshot_that_predates_it(
        repo, tmp_path, monkeypatch, capsys):
    from hermes_cli import main as hermes_main
    from hermes_cli import update_cmd

    home = tmp_path / "home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("hermes_cli.backup._sibling_profile_homes", lambda h: [])
    monkeypatch.setattr(update_cmd._commit, "preflight_refusal", lambda *a, **k: None)
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    _ledgered_store(home)
    _pre_cutover_snapshot(home, "20261001-000000-pre-update")
    # A newer snapshot already holding the runtime ledger is not a way back.
    newer = home / "state-snapshots" / "20261008-000000-pre-update"
    newer.mkdir()
    with closing(sqlite3.connect(newer / "state.db")) as conn:
        conn.execute("CREATE TABLE session_admissions (seq INTEGER)")
    head = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(SystemExit) as stopped:
        update_cmd._refuse_before_commit_point(["git"], _git(repo, "rev-parse", "old-release"), None)
    assert stopped.value.code == 1 and _git(repo, "rev-parse", "HEAD") == head
    out = capsys.readouterr().out
    assert "Downgrading is unsupported" in out and str(home / "state.db") in out
    assert "/snapshot restore 20261001-000000-pre-update" in out and "20261008" not in out
    assert "hermes gateway stop" in out and "No update was applied" in out


def test_forward_updates_and_stores_without_ledger_rows_are_never_refused(repo, tmp_path, monkeypatch):
    monkeypatch.setattr("hermes_cli.backup._sibling_profile_homes", lambda h: [])
    old = _git(repo, "rev-parse", "old-release")
    plain = tmp_path / "plain"
    plain.mkdir()
    SessionDB(plain / "state.db").close()  # runtime tables exist, but nothing was ever admitted
    assert guard.downgrade_refusal(["git"], repo, old, home=plain) is None

    ledgered = tmp_path / "ledgered"
    _ledgered_store(ledgered)
    head = _git(repo, "rev-parse", "HEAD")
    assert guard.downgrade_refusal(["git"], repo, head, home=ledgered) is None
    _git(repo, "checkout", "-q", "--detach", old)  # running the old release: the newer target is forward
    assert guard.downgrade_refusal(["git"], repo, head, home=ledgered) is None


def test_forward_only_waits_for_next_release_when_target_predates_runtime(repo, tmp_path, monkeypatch):
    """an unchosen default subscription only moves forward; a target that predates the runtime leaves head intact."""
    from hermes_cli import source_releases
    from hermes_cli.source_releases import SourceTarget

    home = tmp_path / "home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _ledgered_store(home)
    old = _git(repo, "rev-parse", "old-release")
    head = _git(repo, "rev-parse", "HEAD")

    # when commit is resolved with forward_only it detects the pre-runtime release and keeps head ahead
    monkeypatch.setattr(source_releases, "_resolve_source_target",
                        lambda *a, **k: SourceTarget("stable", "stable", "NousResearch/hermes-agent", commit=old, version="0.22.2"))
    target = source_releases.resolve_source_target("stable", ["git"], repo, forward_only=True)
    assert target.ahead is True
    assert target.commit == head
    assert "this checkout is newer and waits for the next release" in target.label

    # an explicit downgrade without forward_only keeps the old commit so the guard refuses it
    explicit = source_releases.resolve_source_target("stable", ["git"], repo, forward_only=False)
    assert explicit.ahead is False
    assert explicit.commit == old


def test_post_fetch_pre_runtime_release_marks_target_as_head_under_forward_only(repo, tmp_path, monkeypatch, capsys):
    """a fetched pre-runtime release retargets to head and finishes cleanly as up to date under forward_only."""
    from hermes_cli import main, update_cmd

    home = tmp_path / "home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _ledgered_store(home)
    old = _git(repo, "rev-parse", "old-release")
    head = _git(repo, "rev-parse", "HEAD")

    # configure mock options and dependencies
    opts = update_cmd._UpdateOptions(
        pre_update_version=None, gw_input_fn=None,
        assume_yes=True, keep_stash=False, switch_branch=False, discard_local_changes=False,
    )
    monkeypatch.setattr(update_cmd, "_resolve_update_options", lambda *_: opts)
    monkeypatch.setattr(update_cmd, "_begin_update_receipt_and_plan", lambda *_: None)
    monkeypatch.setattr(main, "_run_pre_update_backup", lambda *_: None)
    monkeypatch.setattr(main, "_pause_windows_gateways_for_update", lambda: None)
    monkeypatch.setattr(update_cmd, "_prepare_git_command", lambda **_: (False, ["git"], False))
    monkeypatch.setattr(update_cmd, "_complete_source_update", lambda request: None)
    monkeypatch.setattr(main, "PROJECT_ROOT", repo)
    monkeypatch.setattr(main, "_resolve_update_branch", lambda *_: "main")

    # simulate select_apply_target returning the newly fetched release target before local ancestry is known
    monkeypatch.setattr(
        update_cmd._check, "select_apply_target",
        lambda *a, **k: (old, old, False, "NousResearch/hermes-agent"),
    )
    def fake_source_completion_request(*a, **k):
        return {
            "home": str(home),
            "forward_only": True,
            "release_version": "0.22.2",
            "release_channel": "stable",
            "expected_sha": old,
        }
    monkeypatch.setattr(update_cmd, "_source_completion_request", fake_source_completion_request)
    monkeypatch.setattr("hermes_cli.gitlock.fetch_with_partial_clone_recovery",
                        lambda *a, **k: subprocess.CompletedProcess([], 0))

    args = SimpleNamespace(branch=None, channel=None, yes=True, force=False)
    update_cmd._cmd_update_impl(args, False)

    out = capsys.readouterr().out
    assert "this checkout is newer and waits for the next release" in out
    assert _git(repo, "rev-parse", "HEAD") == head
