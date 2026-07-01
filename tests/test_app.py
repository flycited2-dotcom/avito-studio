import sys
from avito_studio.app import default_bridge_root, _FROZEN_BRIDGE_ROOT


def test_default_bridge_root_uses_fixed_path_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert default_bridge_root() == _FROZEN_BRIDGE_ROOT


def test_default_bridge_root_resolves_relative_when_not_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    root = default_bridge_root()
    assert root.name == "avito-bridge"
    assert (root / "config" / "config.yaml").exists()   # реальный checkout рядом с avito-studio
