"""Docker assembly must keep its prepared dependency selection (#135329)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import sysconfig

import pytest

from docker.build_agent import assemble_image
from scripts.build.inputs import RESOURCE_ENV


def _image_layout(root: Path) -> None:
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname="image-fixture"\nversion="1"\n[project.scripts]\n', encoding="utf-8"
    )
    environment = root / ".venv"
    (environment / "bin").mkdir(parents=True)
    (environment / "bin/python").symlink_to(sys.executable)
    site = Path(sysconfig.get_path("purelib", vars={"base": str(environment), "platbase": str(environment)}))
    site.mkdir(parents=True)
    for name in (*RESOURCE_ENV, "tools", "pm-runtime", "ui-tui/dist", "hermes_cli/web_dist"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "pm-runtime/deps").mkdir()
    (root / "pm-runtime/pm-runtime.json").write_text(
        json.dumps({"python": "../.venv/bin/python", "sitePackages": "deps"}), encoding="utf-8"
    )
    (root / "ui-tui/dist/entry.js").write_text("export {}", encoding="utf-8")
    (root / "ui-tui/package.json").write_text('{"type":"module"}', encoding="utf-8")
    (root / "hermes_cli/web_dist/index.html").write_text("built", encoding="utf-8")


@pytest.mark.platforms("linux")
def test_image_assembly_refuses_missing_feature_inventory(tmp_path):
    root = tmp_path / "image"
    _image_layout(root)
    with pytest.raises(FileNotFoundError, match="enabled-features.json"):
        assemble_image(root)
    assert not (root / "manifest.json").exists()


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("build_succeeds", [False, True])
def test_prepared_image_retains_features_only_after_success(tmp_path, monkeypatch, build_succeeds):
    from types import SimpleNamespace

    from docker import build_dependencies
    from pm.features import read_features
    from pm.install import _target_selection

    root = tmp_path / "image"
    _image_layout(root)
    prepared = []

    def prepare(**kwargs):
        assert kwargs["source"] == root
        assert kwargs["out"] == root / ".venv"
        assert kwargs["python"] == Path(sys.executable)
        assert kwargs["no_install_project"] and kwargs["frozen"]
        assert kwargs["sealed"] and kwargs["explicit"]
        assert not (root / "enabled-features.json").exists()
        prepared.extend(kwargs["extras"])
        if not build_succeeds:
            raise RuntimeError("dependency preparation failed")
        return root / ".venv/bin/python"

    monkeypatch.setattr(build_dependencies, "build_environment", prepare)
    if not build_succeeds:
        with pytest.raises(RuntimeError, match="dependency preparation failed"):
            build_dependencies.build_image_dependencies(root, Path(sys.executable))
        assert not (root / "enabled-features.json").exists()
        with pytest.raises(FileNotFoundError, match="enabled-features.json"):
            assemble_image(root)
        return

    build_dependencies.build_image_dependencies(root, Path(sys.executable))
    inventory = (root / "enabled-features.json").read_bytes()
    assert json.loads(inventory)["extras"] == sorted(prepared)
    assemble_image(root)
    assert (root / "enabled-features.json").read_bytes() == inventory
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(root / "tools"))
    assert read_features() == sorted(prepared)

    declared = set(prepared) | {"discord"}
    with (root / "pyproject.toml").open("a", encoding="utf-8") as stream:
        stream.write("[project.optional-dependencies]\n")
        stream.writelines(f'"{extra}" = []\n' for extra in sorted(declared))
    package = SimpleNamespace(
        project_root=lambda: root,
        expected_stamp=lambda extras, **kwargs: ",".join(extras),
    )
    first, _, _ = _target_selection(
        package, {}, extras=["discord"], inputs={}, repair=False,
        shipped=read_features(), frozen=None,
    )
    assert first == sorted(declared)
    subsequent, _, _ = _target_selection(
        package, {"extras": ["discord"]}, extras=[], inputs={}, repair=False,
        shipped=read_features(), frozen=None,
    )
    assert subsequent == ["discord"]
