"""A removed duplicate credential must not leave a dead secondary status (#146125)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.status import flush_runtime_status, read_runtime_status, write_runtime_status
from tests.gateway.test_multiplex_hot_serve import _mkprofile, _runner


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["credential", "disabled", "removed"])
async def test_removed_duplicate_credential_clears_secondary_status(tmp_path, monkeypatch, change):
    runner, home = _runner(tmp_path, monkeypatch)
    del runner._start_one_profile_adapters
    monkeypatch.setattr("hermes_cli.profiles.get_active_profile_name", lambda: "default")
    runner._register_config_hooks = lambda *args, **kwargs: None
    runner._busy_text_modes_by_profile = {}
    runner._busy_input_modes_by_profile = {}
    profile = _mkprofile(home, "worker", "TELEGRAM_BOT_TOKEN=shared-test-token\n")
    (profile / "config.yaml").write_text(
        "model: {default: test}\nplatforms:\n  telegram:\n    enabled: true\n", encoding="utf-8"
    )
    adapter = SimpleNamespace(token="shared-test-token", platform=Platform.TELEGRAM)
    runner.adapters[Platform.TELEGRAM] = adapter
    runner._create_adapter = lambda platform, config: SimpleNamespace(
        token=config.token, platform=platform
    )
    runner._note_served_profiles([("default", home), ("worker", profile)])
    write_runtime_status(platform="telegram", platform_state="connected")
    claim = runner._adapter_credential_claim(Platform.TELEGRAM, adapter)
    assert await runner._start_one_profile_adapters("worker", profile, {claim: "default"}) == 0
    assert flush_runtime_status()
    before = read_runtime_status()
    assert before["platforms"]["worker:telegram"]["error_code"] == "duplicate_credential"
    assert not runner._profile_adapters["worker"]
    (profile / ".env").write_text("", encoding="utf-8")
    if change != "credential":
        config = "model: {default: test}\n"
        if change == "disabled":
            config += "platforms:\n  telegram:\n    enabled: false\n"
        (profile / "config.yaml").write_text(config, encoding="utf-8")
    result = await runner.reconcile_served_profiles(reason="watcher")
    assert result["rescanned"] == ["worker"]
    assert flush_runtime_status()
    after = read_runtime_status()
    assert after["platforms"]["telegram"]["state"] == "connected"
    assert "worker:telegram" not in after["platforms"]


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["live", "queued", "credential"])
async def test_rescan_preserves_status_still_owned_by_runtime_or_config(tmp_path, monkeypatch, owner):
    runner, home = _runner(tmp_path, monkeypatch)
    del runner._start_one_profile_adapters
    profile = _mkprofile(home, "worker")
    config = GatewayConfig(platforms={})
    if owner == "credential":
        config.platforms[Platform.TELEGRAM] = PlatformConfig(enabled=True, token="still-owned")
    elif owner == "live":
        runner._profile_adapters["worker"] = {Platform.TELEGRAM: object()}
    else:
        runner._profile_failed_platforms["worker"] = {Platform.TELEGRAM: object()}
    runner._load_secondary_profile_config = AsyncMock(return_value=config)
    runner._create_adapter = lambda *args: None
    for key in ("telegram", "worker:telegram", "other:telegram", "worker:discord"):
        write_runtime_status(platform=key, platform_state="retrying", error_code="test_error")
    before = read_runtime_status()["platforms"]
    await runner._start_one_profile_adapters("worker", profile, {})
    assert flush_runtime_status()
    after = read_runtime_status()["platforms"]
    assert "worker:discord" not in after
    for key in ("telegram", "worker:telegram", "other:telegram"):
        assert after[key] == before[key]


@pytest.mark.asyncio
async def test_failed_config_load_keeps_previous_status(tmp_path, monkeypatch):
    runner, home = _runner(tmp_path, monkeypatch)
    del runner._start_one_profile_adapters
    runner._load_secondary_profile_config = AsyncMock(side_effect=ValueError("invalid config"))
    write_runtime_status(platform="worker:telegram", platform_state="fatal", error_code="duplicate_credential")
    before = read_runtime_status()["platforms"]
    with pytest.raises(ValueError, match="invalid config"):
        await runner._start_one_profile_adapters("worker", home, {})
    assert flush_runtime_status()
    assert read_runtime_status()["platforms"] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,error", [
    (Platform.WHATSAPP, "whatsapp_unpaired"),
    (Platform.RELAY, "multiplex_shared_ingress"),
])
async def test_unserved_notice_survives_rescan_and_returns_after_reenable(tmp_path, monkeypatch, platform, error):
    runner, home = _runner(tmp_path, monkeypatch)
    del runner._start_one_profile_adapters
    profile = _mkprofile(home, "worker")
    config = GatewayConfig(platforms={platform: PlatformConfig(enabled=True)})
    runner._load_secondary_profile_config = AsyncMock(return_value=config)
    for _ in range(2):
        assert await runner._start_one_profile_adapters("worker", profile, {}) == 0
        assert flush_runtime_status()
        assert read_runtime_status()["platforms"][f"worker:{platform.value}"]["error_code"] == error
    config.platforms[platform].enabled = False
    await runner._start_one_profile_adapters("worker", profile, {})
    assert flush_runtime_status()
    assert f"worker:{platform.value}" not in read_runtime_status()["platforms"]
    config.platforms[platform].enabled = True
    await runner._start_one_profile_adapters("worker", profile, {})
    assert flush_runtime_status()
    assert read_runtime_status()["platforms"][f"worker:{platform.value}"]["error_code"] == error


def test_atomic_profile_pruning_preserves_other_namespaces(tmp_path, monkeypatch):
    _runner(tmp_path, monkeypatch)
    for key in ("telegram", "worker:telegram", "worker:discord", "worker-two:telegram"):
        write_runtime_status(platform=key, platform_state="connected")
    write_runtime_status(drop_profile_platforms="worker", retain_profile_platforms={"worker:telegram"})
    assert set(read_runtime_status()["platforms"]) == {"telegram", "worker:telegram", "worker-two:telegram"}
    write_runtime_status(drop_profile_platforms="worker")
    assert set(read_runtime_status()["platforms"]) == {"telegram", "worker-two:telegram"}
    write_runtime_status(clear_profile_platforms=True)
    assert set(read_runtime_status()["platforms"]) == {"telegram"}
