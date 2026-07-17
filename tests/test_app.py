import sys
from avito_studio.app import default_bridge_root, default_ssh_key, _FROZEN_BRIDGE_ROOT


def test_default_bridge_root_uses_fixed_path_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert default_bridge_root() == _FROZEN_BRIDGE_ROOT


def test_default_bridge_root_resolves_relative_when_not_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    root = default_bridge_root()
    assert root.name == "avito-bridge"
    assert (root / "config" / "config.yaml").exists()   # реальный checkout рядом с avito-studio


def test_default_ssh_key_uses_first_existing_known_key(tmp_path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "splithome_vps").write_text("key", encoding="utf-8")
    (ssh_dir / "id_ritualb2b_claude").write_text("key", encoding="utf-8")

    assert default_ssh_key(tmp_path) == str(ssh_dir / "id_ritualb2b_claude")


def test_default_ssh_key_keeps_actionable_fallback_when_none_exist(tmp_path):
    assert default_ssh_key(tmp_path) == str(tmp_path / ".ssh" / "id_ritualb2b_admin")
