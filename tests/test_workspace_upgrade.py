from __future__ import annotations

import json
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from avito_studio import workspace_upgrade
from avito_studio.workspace_upgrade import (
    WORKSPACE_MANIFEST,
    WORKSPACE_SCHEMA_VERSION,
    WORKSPACE_TEMPLATE_VERSION,
    WorkspaceUpgradeError,
    ensure_workspace,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _template(root: Path) -> Path:
    _write(
        root / "config" / "config.yaml",
        "profile:\n"
        "  name: conditioners\n"
        "feed:\n"
        "  max_active_ads: 100\n"
        "  min_active_ads: 40\n"
        "  max_drop_fraction: 0.35\n",
    )
    _write(
        root / "profiles" / "wreaths.yaml",
        "profile:\n"
        "  name: wreaths\n"
        "feed:\n"
        "  max_active_ads: 100\n"
        "  min_active_ads: 40\n"
        "  max_drop_fraction: 0.35\n",
    )
    _write(
        root / "avito-descriptions" / "manifest.json",
        '{"conditioners": "default.txt"}\n',
    )
    _write(root / "avito-descriptions" / "default.txt", "Default description\n")
    _write(root / "data" / "supplier-private.csv", "supplier,secret\n")
    return root


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_first_install_is_versioned_and_excludes_supplier_data(tmp_path):
    template = _template(tmp_path / "template")
    target = tmp_path / "local" / "bridge"

    assert ensure_workspace(template, target) == target.resolve()

    assert (target / "config" / "config.yaml").is_file()
    assert (target / "profiles" / "wreaths.yaml").is_file()
    assert (target / "avito-descriptions" / "default.txt").is_file()
    assert not (target / "data").exists()
    assert all((target / name).is_dir() for name in ("feed_out", "state", "runtime"))
    manifest = json.loads((target / WORKSPACE_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == WORKSPACE_SCHEMA_VERSION
    assert manifest["template_version"] == WORKSPACE_TEMPLATE_VERSION
    assert "data" not in manifest["managed_directories"]


def test_repeat_with_current_manifest_is_a_true_no_op(tmp_path, monkeypatch):
    template = _template(tmp_path / "template")
    target = ensure_workspace(template, tmp_path / "local" / "bridge")
    config = target / "config" / "config.yaml"
    config.write_text("user: customized\n", encoding="utf-8")
    before = _files(target)

    monkeypatch.setattr(
        workspace_upgrade.shutil,
        "copytree",
        lambda *args, **kwargs: pytest.fail("current workspace must not be staged"),
    )

    assert ensure_workspace(template, target) == target
    assert _files(target) == before


def test_legacy_upgrade_preserves_values_and_adds_missing_safety_defaults(tmp_path):
    template = _template(tmp_path / "template")
    _write(
        template / "profiles" / "appliances.yaml",
        "profile:\n  name: appliances\nfeed:\n  min_active_ads: 100\n",
    )
    _write(template / "avito-descriptions" / "new.txt", "New default\n")
    target = tmp_path / "local" / "bridge"
    _write(
        target / "config" / "config.yaml",
        "# Keep this user comment\n"
        "profile:\n"
        "  name: my-custom-profile\n"
        "feed:\n"
        "  max_active_ads: 17\n",
    )
    _write(
        target / "profiles" / "wreaths.yaml",
        "profile:\n"
        "  name: my-wreaths\n"
        "feed:\n"
        "  max_active_ads: 55\n",
    )
    _write(target / "data" / "user-import.csv", "user,data\n")
    _write(target / "avito-descriptions" / "default.txt", "My description\n")

    ensure_workspace(template, target)

    yaml = YAML(typ="safe")
    config_text = (target / "config" / "config.yaml").read_text(encoding="utf-8")
    config = yaml.load(config_text)
    profile = yaml.load(
        (target / "profiles" / "wreaths.yaml").read_text(encoding="utf-8")
    )
    assert "# Keep this user comment" in config_text
    assert config["profile"]["name"] == "my-custom-profile"
    assert config["feed"] == {
        "max_active_ads": 17,
        "min_active_ads": 40,
        "max_drop_fraction": 0.35,
    }
    assert profile["profile"]["name"] == "my-wreaths"
    assert profile["feed"]["max_active_ads"] == 55
    assert profile["feed"]["min_active_ads"] == 40
    assert profile["feed"]["max_drop_fraction"] == 0.35
    assert (target / "profiles" / "appliances.yaml").is_file()
    assert (target / "avito-descriptions" / "new.txt").is_file()
    assert (target / "avito-descriptions" / "default.txt").read_text(
        encoding="utf-8"
    ) == "My description\n"
    assert (target / "data" / "user-import.csv").read_text(encoding="utf-8") == (
        "user,data\n"
    )


def test_upgrade_adds_description_manifest_entries_without_overwriting_user_map(
    tmp_path,
):
    template = _template(tmp_path / "template")
    _write(
        template / "avito-descriptions" / "manifest.json",
        json.dumps(
            {
                "conditioners": "default.txt",
                "new-series": "new.txt",
            }
        ),
    )
    _write(template / "avito-descriptions" / "new.txt", "New bundled text\n")
    target = tmp_path / "local" / "bridge"
    _write(target / "config" / "config.yaml", "profile: {name: user}\n")
    _write(
        target / "avito-descriptions" / "manifest.json",
        json.dumps(
            {
                "conditioners": "my-default.txt",
                "user-series": "user.txt",
            }
        ),
    )
    _write(
        target / "avito-descriptions" / "my-default.txt",
        "User replacement\n",
    )
    _write(target / "avito-descriptions" / "user.txt", "User-only text\n")

    ensure_workspace(template, target)

    manifest = json.loads(
        (target / "avito-descriptions" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest == {
        "conditioners": "my-default.txt",
        "user-series": "user.txt",
        "new-series": "new.txt",
    }
    assert (
        target / "avito-descriptions" / "my-default.txt"
    ).read_text(encoding="utf-8") == "User replacement\n"
    assert (
        target / "avito-descriptions" / "new.txt"
    ).read_text(encoding="utf-8") == "New bundled text\n"


def test_upgrade_rolls_back_complete_workspace_when_final_swap_fails(
    tmp_path, monkeypatch
):
    template = _template(tmp_path / "template")
    target = tmp_path / "local" / "bridge"
    _write(
        target / "config" / "config.yaml",
        "feed:\n  max_active_ads: 23\n",
    )
    _write(target / "user-note.txt", "must survive byte-for-byte\n")
    before = _files(target)
    real_replace = workspace_upgrade.os.replace
    failed = False

    def fail_final_swap(source, destination):
        nonlocal failed
        if (
            not failed
            and Path(source).name == "workspace"
            and Path(destination).resolve() == target.resolve()
        ):
            failed = True
            raise OSError("injected final swap failure")
        return real_replace(source, destination)

    monkeypatch.setattr(workspace_upgrade.os, "replace", fail_final_swap)

    with pytest.raises(WorkspaceUpgradeError, match="restored"):
        ensure_workspace(template, target)

    assert failed is True
    assert _files(target) == before
    assert not (target / WORKSPACE_MANIFEST).exists()


def test_failed_upgrade_and_rollback_retains_recoverable_workspace(
    tmp_path, monkeypatch
):
    template = _template(tmp_path / "template")
    target = tmp_path / "local" / "bridge"
    _write(target / "config" / "config.yaml", "feed:\n  max_active_ads: 23\n")
    _write(target / "user-note.txt", "irreplaceable user data\n")
    before = _files(target)
    real_replace = workspace_upgrade.os.replace

    def fail_promotion_and_rollback(source, destination):
        source = Path(source)
        destination = Path(destination)
        if (
            destination.resolve() == target.resolve()
            and (
                source.name == "workspace"
                or source.name.startswith(f".{target.name}.previous-")
            )
        ):
            raise OSError("injected disk failure")
        return real_replace(source, destination)

    monkeypatch.setattr(
        workspace_upgrade.os, "replace", fail_promotion_and_rollback
    )

    with pytest.raises(WorkspaceUpgradeError, match="remains at"):
        ensure_workspace(template, target)

    assert not target.exists()
    retained = list(target.parent.glob(f".{target.name}.previous-*"))
    assert len(retained) == 1
    assert _files(retained[0]) == before
