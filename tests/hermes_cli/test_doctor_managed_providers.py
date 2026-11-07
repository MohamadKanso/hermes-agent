"""doctor validates the provider routes that managed config actually supplies."""

import hermes_yaml as yaml

from hermes_cli import doctor_config


def test_doctor_accepts_managed_provider_for_user_model(tmp_path, monkeypatch):
    home = tmp_path / "home"
    managed = tmp_path / "managed"
    home.mkdir()
    managed.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    config = home / "config.yaml"
    config.write_text(yaml.safe_dump({"model": {"provider": "managed-route", "default": "example"}}), encoding="utf-8")
    (managed / "config.yaml").write_text(yaml.safe_dump({"providers": {"managed-route": {
        "name": "managed-route", "base_url": "https://example.invalid/v1", "default_model": "example"
    }}}), encoding="utf-8")

    issues = []
    doctor_config._validate_model_config(config, issues)

    assert not any("unknown" in issue and "managed-route" in issue for issue in issues)


def test_doctor_reports_unresolvable_managed_auxiliary(tmp_path, monkeypatch):
    home = tmp_path / "home"
    managed = tmp_path / "managed"
    home.mkdir()
    managed.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    config = home / "config.yaml"
    config.write_text("{}\n", encoding="utf-8")
    (managed / "config.yaml").write_text(yaml.safe_dump({"auxiliary": {
        "compression": {"provider": "no-such-managed-provider", "model": "example"}
    }}), encoding="utf-8")

    issues = []
    doctor_config._validate_auxiliary_config(config, issues)

    assert any("auxiliary.compression" in issue and "no-such-managed-provider" in issue for issue in issues)


def test_doctor_checks_managed_routes_without_user_config(tmp_path, monkeypatch, capsys):
    from hermes_cli import doctor

    home = tmp_path / "home"
    managed = tmp_path / "managed"
    home.mkdir()
    managed.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    monkeypatch.setattr(doctor, "HERMES_HOME", home)
    (managed / "config.yaml").write_text(yaml.safe_dump({"auxiliary": {
        "compression": {"provider": "no-such-managed-provider", "model": "example"}
    }}), encoding="utf-8")

    finding = doctor_config._check_config_file(False)

    assert "config.yaml not found" in capsys.readouterr().out
    assert any("auxiliary.compression" in issue and "no-such-managed-provider" in issue for issue in finding.issues)
    assert not (home / "config.yaml").exists()
