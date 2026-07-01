from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from avito_studio.ssh_client import SshClient
from avito_studio.main_window import MainWindow

# Путь checkout'а avito-bridge на этой машине. В .exe (PyInstaller --onefile) __file__
# указывает во временную распаковку (_MEIxxxxx), а не на реальные исходники на диске —
# относительный расчёт "..от __file__.." там даёт мусорный путь. Поэтому во frozen-сборке
# используем фиксированный абсолютный путь; при запуске из исходников — относительный (dev-режим).
_FROZEN_BRIDGE_ROOT = Path(r"C:\Users\user\Documents\GitHub\Codex\Avito\avito-bridge")
DEFAULT_SSH_HOST = "root@213.109.202.45"
DEFAULT_SSH_KEY = str(Path.home() / ".ssh" / "climat_simf_deploy")


def default_bridge_root() -> Path:
    if getattr(sys, "frozen", False):
        return _FROZEN_BRIDGE_ROOT
    return Path(__file__).resolve().parents[3] / "avito-bridge"


def main() -> int:
    app = QApplication(sys.argv)
    bridge_root = default_bridge_root()
    ssh = SshClient(host=DEFAULT_SSH_HOST, key_path=DEFAULT_SSH_KEY)
    win = MainWindow(bridge_root=bridge_root,
                     config_path=bridge_root / "config" / "config.yaml", ssh=ssh)
    win.resize(1000, 600)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
