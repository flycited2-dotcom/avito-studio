from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from avito_studio.ssh_client import SshClient
from avito_studio.main_window import MainWindow
from avito_studio.theme import apply_theme

# Путь checkout'а avito-bridge на этой машине. В .exe (PyInstaller --onefile) __file__
# указывает во временную распаковку (_MEIxxxxx), а не на реальные исходники на диске —
# относительный расчёт "..от __file__.." там даёт мусорный путь. Поэтому во frozen-сборке
# используем путь текущего Windows-пользователя; при запуске из исходников — относительный.
_FROZEN_BRIDGE_ROOT = Path.home() / "Documents" / "GitHub" / "Codex" / "Avito" / "avito-bridge"
DEFAULT_SSH_HOST = "root@213.109.202.45"
SSH_KEY_NAMES = (
    "id_ritualb2b_admin",
    "id_ritualb2b_claude",
    "splithome_vps",
    "climat_simf_deploy",
)


def default_bridge_root() -> Path:
    if getattr(sys, "frozen", False):
        return _FROZEN_BRIDGE_ROOT
    return Path(__file__).resolve().parents[3] / "avito-bridge"


def default_ssh_key(home: Path | None = None) -> str:
    ssh_dir = Path(home) / ".ssh" if home is not None else Path.home() / ".ssh"
    for name in SSH_KEY_NAMES:
        candidate = ssh_dir / name
        if candidate.is_file():
            return str(candidate)
    return str(ssh_dir / SSH_KEY_NAMES[0])


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    bridge_root = default_bridge_root()
    ssh = SshClient(host=DEFAULT_SSH_HOST, key_path=default_ssh_key())
    win = MainWindow(bridge_root=bridge_root,
                     config_path=bridge_root / "config" / "config.yaml", ssh=ssh)
    win.resize(1360, 820)
    win.show()
    QTimer.singleShot(200, win.refresh)   # каталог грузится сам — не заставляем жать «Обновить»
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
