# owner attachments survive age sweep while platform inbound media gets collected
import os
import time

from gateway.session_ingress_media import (
    capture_native_media,
    release_admission_media,
    release_unheld_media,
    sweep_settled_media,
)
from hermes_state import SessionDB
from hermes_state_media import collect_retired_media, retire_media
from hermes_state_runtime import admit_session_input, begin_runtime_epoch, claim_session_input, settle_session_input


def _create_settled_admission(tmp_path, monkeypatch, *, field_name):
    from gateway.platforms.base import get_document_cache_dir
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    staged = get_document_cache_dir() / f"test_{field_name}.png"
    staged.write_bytes(b"\x89png\r\n\x1a\nfakeimagebytes")
    media = capture_native_media([staged])
    retained = media[0]["path"]
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("s", source="desktop")
    db.append_message("s", "user", f"look at this\n\n[Image attached at: {retained}]")
    epoch = begin_runtime_epoch(db, instance_id="owner")
    payload = {"text": "look at this"}
    payload[field_name] = {"media": media}
    row = admit_session_input(
        db,
        epoch=epoch,
        principal_id="owner_user",
        session_id="s",
        request_id="req_1",
        payload=payload,
    )
    claim = claim_session_input(db, epoch=epoch, session_id="s")
    settle_session_input(
        db,
        epoch=epoch,
        admission_id=row["admission_id"],
        generation=claim["generation"],
        outcome="completed",
    )
    return db, row, retained, payload


def test_owner_attachments_survive_hourly_age_sweep(tmp_path, monkeypatch):
    import gateway.session_ingress_media as media_module
    monkeypatch.setattr(media_module, "_last_sweep", {}, raising=False)
    db, row, retained, payload = _create_settled_admission(tmp_path, monkeypatch, field_name="attachments_v1")
    try:
        assert os.path.exists(retained)
        # age past 24 hours
        old = time.time() - 25 * 3600
        os.utime(retained, (old, old))
        monkeypatch.setattr(media_module, "_last_sweep", {}, raising=False)

        # age sweep should not delete owner attachments
        sweep_count = sweep_settled_media(db)
        assert sweep_count == 0
        assert os.path.exists(retained)

        # release_admission_media also leaves it retained because transcript names it
        monkeypatch.setattr(media_module, "_last_sweep", {}, raising=False)
        release_admission_media(db, row["admission_id"])
        assert os.path.exists(retained)

        # session retirement / unheld release cleans it up once transcript is retired
        db._execute_write(lambda conn: retire_media(conn, payload))
        collect_retired_media(db)
        release_unheld_media(db, payload["attachments_v1"]["media"], retain_history=False)
        assert not os.path.exists(retained)
    finally:
        db.close()


def test_platform_inbound_media_is_collected_by_age_sweep(tmp_path, monkeypatch):
    import gateway.session_ingress_media as media_module
    monkeypatch.setattr(media_module, "_last_sweep", {}, raising=False)
    db, _row, retained, _payload = _create_settled_admission(tmp_path, monkeypatch, field_name="native_text_v1")
    try:
        assert os.path.exists(retained)
        # age past 24 hours
        old = time.time() - 25 * 3600
        os.utime(retained, (old, old))
        monkeypatch.setattr(media_module, "_last_sweep", {}, raising=False)

        # age sweep must collect platform inbound media even if transcript named it
        sweep_count = sweep_settled_media(db)
        assert sweep_count >= 1
        assert not os.path.exists(retained)
    finally:
        db.close()
