from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from avito_studio.ssh_client import SshClient
from avito_studio.main_window import MainWindow

DEFAULT_BRIDGE_ROOT = Path(__file__).resolve().parents[3] / "avito-bridge"
DEFAULT_SSH_HOST = "root@213.109.202.45"
DEFAULT_SSH_KEY = str(Path.home() / ".ssh" / "climat_simf_deploy")


def main() -> int:
    app = QApplication(sys.argv)
    ssh = SshClient(host=DEFAULT_SSH_HOST, key_path=DEFAULT_SSH_KEY)
    win = MainWindow(bridge_root=DEFAULT_BRIDGE_ROOT,
                     config_path=DEFAULT_BRIDGE_ROOT / "config" / "config.yaml", ssh=ssh)
    win.resize(1000, 600)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
