from __future__ import annotations

import os
import logging
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avito_studio.main_window import MainWindow
from avito_studio.diagnostics import configure_logging
from avito_studio.profiles import PROFILES
from avito_studio.ssh_client import SshClient
from avito_studio.theme import apply_theme
from avito_studio.version import __version__, bridge_revision
from avito_studio.workspace_upgrade import ensure_workspace

# Путь checkout'а avito-bridge на этой машине. В .exe (PyInstaller --onefile) __file__
# указывает во временную распаковку (_MEIxxxxx), а не на реальные исходники на диске —
# относительный расчёт "..от __file__.." там даёт мусорный путь. Поэтому во frozen-сборке
# используем путь текущего Windows-пользователя; при запуске из исходников — относительный.
_FROZEN_BRIDGE_ROOT = Path.home() / "Documents" / "GitHub" / "Codex" / "Avito" / "avito-bridge"
# A fresh installation must not silently point at production infrastructure.
# The user supplies a host in Settings or through AVITO_STUDIO_SSH_HOST.
DEFAULT_SSH_HOST = ""
SSH_KEY_NAMES = (
    "id_ritualb2b_admin",
    "id_ritualb2b_claude",
    "splithome_vps",
    "climat_simf_deploy",
)
BRIDGE_ROOT_ENV = "AVITO_STUDIO_BRIDGE_ROOT"
_SETTINGS_ORGANIZATION = "AvitoStudio"
_SETTINGS_APPLICATION = "AvitoContentStudio"
_SETTINGS_BRIDGE_ROOT = "bridge_root"
_SETTINGS_SSH_HOST = "ssh_host"
_SETTINGS_SSH_KEY = "ssh_key"
_BUNDLED_TEMPLATE_DIR = "bridge-template"
SSH_HOST_ENV = "AVITO_STUDIO_SSH_HOST"
SSH_KEY_ENV = "AVITO_STUDIO_SSH_KEY"
_SSH_HOST = re.compile(
    r"(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*@)?"
    r"(?:[A-Za-z0-9_.][A-Za-z0-9_.:-]*)\Z"
)


def user_bridge_root(env: Mapping[str, str] | None = None) -> Path:
    environment = os.environ if env is None else env
    local_app_data = environment.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return _normalise_path(base / "AvitoStudio" / "bridge")


def bundled_bridge_template() -> Path | None:
    bundle_root = getattr(sys, "_MEIPASS", "")
    if not bundle_root:
        return None
    candidate = _normalise_path(Path(bundle_root) / _BUNDLED_TEMPLATE_DIR)
    return candidate if is_bridge_root(candidate) else None


def ensure_bundled_workspace(
    template: Path | None = None,
    target: Path | None = None,
    *,
    persist_setting: bool = True,
) -> Path | None:
    """Install or additively upgrade the versioned per-user workspace."""
    destination = _normalise_path(target or user_bridge_root())
    source = _normalise_path(template) if template is not None else bundled_bridge_template()
    if source is None or not is_bridge_root(source):
        return None
    ensure_workspace(source, destination)
    if persist_setting:
        QSettings(_SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION).setValue(
            _SETTINGS_BRIDGE_ROOT, str(destination)
        )
    return destination


def default_bridge_root() -> Path:
    """Return the best root to show in diagnostics, even when it is not installed.

    ``resolve_bridge_root`` is the strict resolver used before constructing the
    main window.  This compatibility helper deliberately always returns a path.
    """
    explicit = os.environ.get(BRIDGE_ROOT_ENV, "").strip()
    if explicit:
        return _normalise_path(explicit)
    resolved = resolve_bridge_root()
    if resolved is not None:
        return resolved
    if getattr(sys, "frozen", False):
        return user_bridge_root()
    return Path(__file__).resolve().parents[3] / "avito-bridge"


def _normalise_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def is_bridge_root(path: str | Path) -> bool:
    """A checkout is usable by Studio only when its primary YAML exists."""
    try:
        root = _normalise_path(path)
    except (OSError, RuntimeError, ValueError):
        return False
    return root.is_dir() and (root / "config" / "config.yaml").is_file()


def bridge_root_candidates() -> tuple[Path, ...]:
    """Known non-destructive lookup locations, ordered from specific to legacy."""
    source_sibling = Path(__file__).resolve().parents[3] / "avito-bridge"
    executable_dir = Path(sys.executable).resolve().parent
    saved = QSettings(
        _SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION
    ).value(_SETTINGS_BRIDGE_ROOT, "")
    raw = (
        saved,
        user_bridge_root(),
        executable_dir / "avito-bridge",
        executable_dir.parent / "avito-bridge",
        source_sibling,
        _FROZEN_BRIDGE_ROOT,
        Path.cwd(),
        Path.cwd() / "avito-bridge",
    )
    result: list[Path] = []
    seen: set[str] = set()
    for value in raw:
        if not value:
            continue
        try:
            candidate = _normalise_path(value)
        except (OSError, RuntimeError, ValueError):
            continue
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return tuple(result)


def resolve_bridge_root(
    env: Mapping[str, str] | None = None,
    candidates: Iterable[str | Path] | None = None,
) -> Path | None:
    """Resolve a verified checkout without guessing past an explicit bad path.

    An invalid ``AVITO_STUDIO_BRIDGE_ROOT`` intentionally returns ``None``:
    silently falling back to a different checkout could publish stale configs.
    """
    environment = os.environ if env is None else env
    explicit = environment.get(BRIDGE_ROOT_ENV, "").strip()
    if explicit:
        candidate = _normalise_path(explicit)
        return candidate if is_bridge_root(candidate) else None
    search = bridge_root_candidates() if candidates is None else candidates
    for value in search:
        if is_bridge_root(value):
            return _normalise_path(value)
    return None


def default_ssh_key(home: Path | None = None) -> str:
    ssh_dir = Path(home) / ".ssh" if home is not None else Path.home() / ".ssh"
    for name in SSH_KEY_NAMES:
        candidate = ssh_dir / name
        if candidate.is_file():
            return str(candidate)
    return str(ssh_dir / SSH_KEY_NAMES[0])


def connection_settings() -> tuple[str, str]:
    settings = QSettings(_SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION)
    host = (
        os.environ.get(SSH_HOST_ENV, "").strip()
        or str(settings.value(_SETTINGS_SSH_HOST, "") or "").strip()
        or DEFAULT_SSH_HOST
    )
    key = (
        os.environ.get(SSH_KEY_ENV, "").strip()
        or str(settings.value(_SETTINGS_SSH_KEY, "") or "").strip()
        or default_ssh_key()
    )
    return host, key


def validate_connection_settings(host: str, key_path: str) -> tuple[str, str]:
    host = str(host).strip()
    if not _SSH_HOST.fullmatch(host) or host.startswith("-"):
        raise ValueError("Хост должен иметь безопасный вид user@server или server.")
    key = _normalise_path(key_path)
    if not key.is_file():
        raise ValueError(f"SSH-ключ не найден: {key}")
    return host, str(key)


def save_connection_settings(host: str, key_path: str) -> tuple[str, str]:
    host, key = validate_connection_settings(host, key_path)
    settings = QSettings(_SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION)
    settings.setValue(_SETTINGS_SSH_HOST, host)
    settings.setValue(_SETTINGS_SSH_KEY, key)
    return host, key


class BridgeSetupWindow(QMainWindow):
    """Small first-run window shown when avito-bridge is not available locally."""

    def __init__(
        self,
        ssh,
        attempted_root: Path | None = None,
        startup_error: str = "",
    ):
        super().__init__()
        self.ssh = ssh
        self.attempted_root = attempted_root
        self._main_window: MainWindow | None = None
        self.setWindowTitle("Avito Content Studio — настройка")
        body = QWidget()
        layout = QVBoxLayout(body)
        title = QLabel("Нужно указать папку avito-bridge")
        title.setObjectName("pageTitle")
        details = (
            "Studio открылась без подключения к серверу. Выберите локальную папку "
            "репозитория avito-bridge, внутри которой есть config/config.yaml."
        )
        if attempted_root is not None:
            details += f"\n\nПроверенный путь не найден:\n{attempted_root}"
        if startup_error:
            details += f"\n\nКонфигурация не открылась:\n{startup_error}"
        message = QLabel(details)
        message.setWordWrap(True)
        choose = QPushButton("Выбрать папку avito-bridge…")
        choose.clicked.connect(self._choose_bridge_root)
        connection = QPushButton("Настроить SSH-подключение…")
        connection.clicked.connect(self._configure_connection)
        layout.addWidget(title)
        layout.addWidget(message)
        layout.addWidget(choose)
        layout.addWidget(connection)
        layout.addStretch(1)
        self.setCentralWidget(body)
        self.resize(720, 320)

    def _configure_connection(self) -> None:
        host, accepted = QInputDialog.getText(
            self,
            "SSH-подключение",
            "Сервер (user@host):",
            text=str(getattr(self.ssh, "host", "")),
        )
        if not accepted:
            return
        key_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите приватный SSH-ключ",
            str(getattr(self.ssh, "key_path", "")),
            "SSH private key (*)",
        )
        if not key_path:
            return
        try:
            host, key_path = save_connection_settings(host, key_path)
        except ValueError as exc:
            QMessageBox.warning(self, "Настройки не сохранены", str(exc))
            return
        self.ssh.host = host
        self.ssh.key_path = key_path
        QMessageBox.information(
            self,
            "Подключение сохранено",
            "Параметры сохранены. Сеть будет проверена только после нажатия «Обновить».",
        )

    def _choose_bridge_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку avito-bridge",
            str(self.attempted_root or Path.home()),
        )
        if not selected:
            return
        root = _normalise_path(selected)
        if not is_bridge_root(root) and is_bridge_root(root / "avito-bridge"):
            root = root / "avito-bridge"
        if not is_bridge_root(root):
            QMessageBox.warning(
                self,
                "Это не avito-bridge",
                f"В выбранной папке нет config/config.yaml:\n{root}",
            )
            return
        QSettings(_SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION).setValue(
            _SETTINGS_BRIDGE_ROOT, str(root)
        )
        try:
            self._main_window = MainWindow(
                bridge_root=root,
                config_path=root / "config" / "config.yaml",
                ssh=self.ssh,
            )
        except Exception as exc:
            self._main_window = None
            QMessageBox.critical(
                self,
                "Конфигурация не открылась",
                f"Не удалось прочитать config/config.yaml:\n{exc}",
            )
            return
        self._main_window.resize(1360, 820)
        self._main_window.show()
        self.close()


def build_initial_window(
    bridge_root: Path | None = None,
    ssh: SshClient | None = None,
    *,
    persist_workspace_setting: bool = True,
) -> QMainWindow:
    """Build an offline-safe first window; no SSH call is made here."""
    if ssh is None:
        host, key = connection_settings()
        client = SshClient(host=host, key_path=key)
    else:
        client = ssh
    workspace_error = ""
    if bridge_root is not None:
        root = _normalise_path(bridge_root)
    elif getattr(sys, "frozen", False):
        if os.environ.get(BRIDGE_ROOT_ENV, "").strip():
            # An explicitly supplied checkout is authoritative in packaged
            # builds too.  Besides being predictable, this makes isolated
            # diagnostics possible without touching the user's QSettings.
            root = resolve_bridge_root(candidates=())
        else:
            try:
                root = ensure_bundled_workspace(
                    persist_setting=persist_workspace_setting
                )
            except Exception as exc:
                root = None
                workspace_error = (
                    "Безопасное обновление локальных шаблонов не выполнено: "
                    f"{exc}"
                )
            if root is None and not workspace_error:
                root = resolve_bridge_root()
    else:
        root = resolve_bridge_root()
    if workspace_error:
        return BridgeSetupWindow(
            client,
            user_bridge_root(),
            startup_error=workspace_error,
        )
    if root is None or not is_bridge_root(root):
        attempted = (
            _normalise_path(bridge_root)
            if bridge_root is not None
            else default_bridge_root()
        )
        return BridgeSetupWindow(client, attempted)
    try:
        return MainWindow(
            bridge_root=root,
            config_path=root / "config" / "config.yaml",
            ssh=client,
        )
    except Exception as exc:
        return BridgeSetupWindow(client, root, startup_error=str(exc))


def run_smoke_checks(window: QMainWindow) -> None:
    """Exercise safe UI invariants inside the real Qt event loop.

    The smoke path deliberately avoids refresh and publication: those actions
    may contact suppliers or production.  Data-changing behavior is covered by
    the isolated pytest and integration suites.
    """
    if not isinstance(window, MainWindow):
        raise RuntimeError("Studio opened the setup window instead of the main window")
    if not window.isVisible():
        raise RuntimeError("The main window was not shown")
    profile_keys = [
        window.profile_combo.itemData(index).key
        for index in range(window.profile_combo.count())
    ]
    expected_keys = [profile.key for profile in PROFILES]
    if profile_keys != expected_keys:
        raise RuntimeError(
            f"Profile registry mismatch: expected {expected_keys}, got {profile_keys}"
        )
    if window._running_threads():
        raise RuntimeError("Startup unexpectedly launched a background operation")
    if window._catalog_loaded:
        raise RuntimeError("Startup unexpectedly loaded a catalog")

    window.nav_catalog.click()
    if window.pages.currentIndex() != 1 or window.page_title.text() != "Каталог":
        raise RuntimeError("Catalog navigation did not activate the catalog page")
    sentinel = "avito-smoke-sentinel"
    window.search.setText(sentinel)
    if (
        window.search.text() != sentinel
        or not window.proxy.filterRegularExpression().pattern()
    ):
        raise RuntimeError("Catalog search did not update its filter")
    window.search.clear()
    if window.proxy.filterRegularExpression().pattern():
        raise RuntimeError("Catalog search did not clear its filter")
    window.nav_overview.click()
    if window.pages.currentIndex() != 0 or window.page_title.text() != "Обзор":
        raise RuntimeError("Overview navigation did not return to the overview page")

    appliances = next(profile for profile in PROFILES if profile.key == "appliances")
    if appliances.publish_enabled or not appliances.publish_block_reason:
        raise RuntimeError("Appliances publication safety guard is not configured")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    smoke_test = "--smoke-test" in arguments
    log_path = configure_logging()
    logging.getLogger(__name__).info(
        "Studio starting; version=%s bridge=%s frozen=%s smoke=%s log=%s",
        __version__,
        bridge_revision(),
        bool(getattr(sys, "frozen", False)),
        smoke_test,
        log_path,
    )
    qt_arguments = [sys.argv[0], *[arg for arg in arguments if arg != "--smoke-test"]]
    app = QApplication(qt_arguments)

    def report_unhandled(exc_type, exc_value, traceback) -> None:
        logging.getLogger(__name__).critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, traceback),
        )
        QMessageBox.critical(
            None,
            "Непредвиденная ошибка",
            f"{exc_value}\n\nПодробности записаны в:\n{log_path}",
        )

    sys.excepthook = report_unhandled
    apply_theme(app)
    win = build_initial_window(persist_workspace_setting=not smoke_test)
    if isinstance(win, MainWindow):
        win.resize(1360, 820)
    win.show()
    if smoke_test:
        # Packaged-process smoke: prove the EXE can unpack its workspace, create
        # and exercise the real first window without contacting production.
        def finish_smoke_test() -> None:
            try:
                run_smoke_checks(win)
            except Exception:
                logging.getLogger(__name__).exception("Studio smoke checks failed")
                app.exit(2)
                return
            logging.getLogger(__name__).info("Studio smoke checks passed")
            app.exit(0)

        QTimer.singleShot(750, finish_smoke_test)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
