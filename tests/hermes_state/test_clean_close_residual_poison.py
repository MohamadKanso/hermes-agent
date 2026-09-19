"""Tests verifying clean SessionDB.close() does not poison residual entry points.

Reproduces and guards against issue #116244:
- optimize_fts()
- rebuild_fts()
- vacuum()
- _execute_write() SQLite-error handling
"""
import json
import sqlite3
import threading
import pytest
from hermes_state import SessionDB


@pytest.mark.parametrize("case", range(5))
@pytest.mark.parametrize("entry", ["normal", "optimize", "rebuild", "vacuum", "error_branch"])
def test_clean_close_never_causes_false_sticky_loss(tmp_path, monkeypatch, entry, case):
    path = tmp_path / "synthetic.db"
    db = SessionDB(db_path=path)
    db.create_session("synthetic", "cli")
    conn = db._conn
    assert db._db_sidecar_identity and path.with_name(path.name + "-wal").exists()
    lock, close, guard = db._lock, db._close_connection_quietly, db._raise_if_db_replaced
    closed, progress, second = threading.Event(), threading.Event(), threading.Event()
    calls = 0
    errors = []
    close_errors = []
    post_errors = []

    def is_writer():
        return threading.current_thread().name == "synthetic-writer"

    class ObservedLock:
        def __enter__(self):
            if is_writer():
                progress.set()
            lock.acquire()
            return self

        def __exit__(self, *args):
            lock.release()
            if is_writer() and entry == "error_branch" and calls == 1:
                second.set()

    def observed_guard():
        nonlocal calls
        if is_writer():
            calls += 1
        try:
            return guard()
        finally:
            if is_writer():
                progress.set()

    def paused_close(connection):
        close(connection)
        if connection is conn:
            assert not path.with_name(path.name + "-wal").exists(), "real close did not end WAL"
            closed.set()
            assert progress.wait(10), "writer reached neither guard nor lock"

    monkeypatch.setattr(db, "_lock", ObservedLock())
    monkeypatch.setattr(db, "_close_connection_quietly", paused_close)
    monkeypatch.setattr(db, "_raise_if_db_replaced", observed_guard)

    def closer():
        try:
            db.close()
        except BaseException as e:
            close_errors.append(type(e).__name__ + ": " + str(e))

    def inject_error(c):
        exc = sqlite3.DatabaseError("fts5: corrupt structure (deliberate synthetic injection)")
        exc.sqlite_errorcode = getattr(sqlite3, "SQLITE_CORRUPT_VTAB", 267)
        raise exc

    def writer():
        try:
            if entry == "normal":
                db.append_message("synthetic", "tool", content="normal-during-close")
            elif entry == "optimize":
                db.optimize_fts()
            elif entry == "rebuild":
                db.rebuild_fts()
            elif entry == "vacuum":
                db.vacuum()
            else:
                db._execute_write(inject_error)
        except BaseException as e:
            errors.append(type(e).__name__ + ": " + str(e))

    tc = threading.Thread(target=closer, name="synthetic-closer")
    tw = threading.Thread(target=writer, name="synthetic-writer")
    try:
        if entry == "error_branch":
            tw.start()
            assert second.wait(10), "second generation guard not reached"
            tc.start()
        else:
            tc.start()
            assert closed.wait(10)
            tw.start()
        tw.join(15)
        tc.join(15)
        assert not tw.is_alive() and not tc.is_alive(), "barrier deadlock is not a safety pass"
        assert not close_errors, close_errors
        assert not any("AssertionError" in x for x in errors), errors
        sticky = bool(db._db_wal_generation_lost)
        try:
            db.append_message("synthetic", "tool", content="after-legitimate-close")
        except Exception as e:
            post_errors.append(type(e).__name__ + ": " + str(e))
        reader = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = reader.execute("SELECT count(*) FROM messages").fetchone()[0]
        finally:
            reader.close()
        observed = {
            "entry": entry,
            "case": case,
            "guard_calls": calls,
            "sticky": sticky,
            "errors": errors,
            "post_errors": post_errors,
            "rows": rows,
            "injected_sqlite_error": entry == "error_branch",
        }
        print("OBSERVED " + json.dumps(observed), flush=True)
        assert not sticky and not post_errors, observed
        assert rows == (2 if entry == "normal" else 1), observed
    finally:
        progress.set()
        closed.set()
        second.set()
        if tc.ident is not None:
            tc.join(15)
        if tw.ident is not None:
            tw.join(15)
        monkeypatch.undo()
        db.close()
