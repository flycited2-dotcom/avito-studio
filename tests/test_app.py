import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from avito_studio.app import (
    BRIDGE_ROOT_ENV,
    BridgeSetupWindow,
    bridge_root_candidates,
    build_initial_window,
    bundled_bridge_template,
    connection_settings,
    default_bridge_root,
    default_ssh_key,
    ensure_bundled_workspace,
    is_bridge_root,
    main,
    resolve_bridge_root,
    run_smoke_checks,
    save_connection_settings,
    SSH_HOST_ENV,
    SSH_KEY_ENV,
    user_bridge_root,
    validate_connection_settings,
)
from avito_studio.main_window import MainWindow


def test_default_bridge_root_uses_local_app_data_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("avito_studio.app.resolve_bridge_root", lambda: None)
    assert default_bridge_root() == user_bridge_root()


def test_default_bridge_root_honours_explicit_path_and_resolver(
    monkeypatch, tmp_path
):
    explicit = tmp_path / "explicit"
    monkeypatch.setenv(BRIDGE_ROOT_ENV, str(explicit))
    assert default_bridge_root() == explicit.resolve()

    monkeypatch.delenv(BRIDGE_ROOT_ENV)
    resolved = tmp_path / "resolved"
    monkeypatch.setattr(
        "avito_studio.app.resolve_bridge_root", lambda: resolved
    )
    assert default_bridge_root() == resolved


def test_default_bridge_root_resolves_relative_when_not_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv(BRIDGE_ROOT_ENV, raising=False)
    monkeypatch.setattr("avito_studio.app.resolve_bridge_root", lambda: None)
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


def _bridge_root(tmp_path):
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "config.yaml").write_text(
        "catalog:\n  selected_series: []\n", encoding="utf-8"
    )
    return tmp_path


def test_resolver_prefers_explicit_verified_environment_path(tmp_path):
    root = _bridge_root(tmp_path / "bridge")
    other = _bridge_root(tmp_path / "other")
    assert resolve_bridge_root(
        env={BRIDGE_ROOT_ENV: str(root)}, candidates=[other]
    ) == root.resolve()


def test_resolver_does_not_silently_ignore_invalid_explicit_path(tmp_path):
    valid = _bridge_root(tmp_path / "valid")
    assert resolve_bridge_root(
        env={BRIDGE_ROOT_ENV: str(tmp_path / "missing")}, candidates=[valid]
    ) is None


def test_resolver_searches_candidates_and_reports_no_match(tmp_path):
    root = _bridge_root(tmp_path / "valid")
    assert resolve_bridge_root(env={}, candidates=[tmp_path / "missing", root]) == (
        root.resolve()
    )
    assert resolve_bridge_root(env={}, candidates=[tmp_path / "missing"]) is None


def test_bridge_root_validation_fails_closed_on_path_resolution_error(
    monkeypatch
):
    monkeypatch.setattr(
        "avito_studio.app._normalise_path",
        lambda _value: (_ for _ in ()).throw(OSError("unreadable")),
    )
    assert is_bridge_root("broken") is False


def test_bundled_template_requires_frozen_bundle_and_valid_checkout(
    monkeypatch, tmp_path
):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert bundled_bridge_template() is None

    bundle = tmp_path / "bundle"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert bundled_bridge_template() is None
    template = _bridge_root(bundle / "bridge-template")
    assert bundled_bridge_template() == template.resolve()


def test_bridge_root_candidates_are_normalized_and_deduplicated(
    monkeypatch, tmp_path
):
    class FakeSettings:
        def __init__(self, *_args):
            pass

        def value(self, *_args):
            return str(tmp_path)

    monkeypatch.setattr("avito_studio.app.QSettings", FakeSettings)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    candidates = bridge_root_candidates()

    assert candidates.count(tmp_path.resolve()) == 1
    assert all(path.is_absolute() for path in candidates)


class _OfflineSsh:
    def __init__(self):
        self.calls = []

    def run(self, command):
        self.calls.append(command)
        raise AssertionError("startup must not access the network")


def test_initial_main_window_opens_without_automatic_refresh(qtbot, tmp_path):
    root = _bridge_root(tmp_path / "bridge")
    ssh = _OfflineSsh()
    window = build_initial_window(root, ssh)
    qtbot.addWidget(window)
    qtbot.wait(300)
    assert isinstance(window, MainWindow)
    assert ssh.calls == []
    assert "Нажмите «Обновить»" in window.statusBar().currentMessage()


def test_frozen_startup_runs_workspace_upgrade_before_opening(qtbot, tmp_path, monkeypatch):
    root = _bridge_root(tmp_path / "bridge")
    calls = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "avito_studio.app.ensure_bundled_workspace",
        lambda *, persist_setting: calls.append(persist_setting) or root,
    )
    monkeypatch.setattr(
        "avito_studio.app.resolve_bridge_root",
        lambda: pytest.fail("successful bundled upgrade is authoritative"),
    )

    window = build_initial_window(ssh=_OfflineSsh())
    qtbot.addWidget(window)

    assert isinstance(window, MainWindow)
    assert calls == [True]


def test_frozen_startup_honours_explicit_root_without_installing_bundle(
    qtbot, tmp_path, monkeypatch
):
    root = _bridge_root(tmp_path / "explicit")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv(BRIDGE_ROOT_ENV, str(root))
    monkeypatch.setattr(
        "avito_studio.app.ensure_bundled_workspace",
        lambda **_kwargs: pytest.fail("explicit root must skip bundle install"),
    )

    window = build_initial_window(ssh=_OfflineSsh())
    qtbot.addWidget(window)

    assert isinstance(window, MainWindow)


def test_frozen_invalid_explicit_root_fails_closed_without_bundle_fallback(
    qtbot, tmp_path, monkeypatch
):
    missing = tmp_path / "missing"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv(BRIDGE_ROOT_ENV, str(missing))
    monkeypatch.setattr(
        "avito_studio.app.ensure_bundled_workspace",
        lambda **_kwargs: pytest.fail("invalid explicit root must not fall back"),
    )

    window = build_initial_window(ssh=_OfflineSsh())
    qtbot.addWidget(window)

    assert isinstance(window, BridgeSetupWindow)
    assert window.attempted_root == missing.resolve()


def test_frozen_workspace_upgrade_failure_opens_safe_setup(
    qtbot, tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        "avito_studio.app.ensure_bundled_workspace",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("rollback complete")),
    )

    window = build_initial_window(ssh=_OfflineSsh())
    qtbot.addWidget(window)

    assert isinstance(window, BridgeSetupWindow)
    assert any(
        "rollback complete" in label.text()
        for label in window.centralWidget().findChildren(QLabel)
    )


def test_missing_checkout_opens_setup_window_instead_of_crashing(qtbot, tmp_path):
    window = build_initial_window(tmp_path / "missing", _OfflineSsh())
    qtbot.addWidget(window)
    assert isinstance(window, BridgeSetupWindow)
    assert "настройка" in window.windowTitle().lower()


def test_malformed_config_opens_setup_window_instead_of_crashing(qtbot, tmp_path):
    root = tmp_path / "bridge"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text(
        "catalog: [unterminated", encoding="utf-8"
    )
    window = build_initial_window(root, _OfflineSsh())
    qtbot.addWidget(window)
    assert isinstance(window, BridgeSetupWindow)


def test_bundled_template_is_copied_once_without_overwriting_user_changes(
    tmp_path, monkeypatch
):
    saved = []

    class FakeSettings:
        def __init__(self, *args):
            pass

        def setValue(self, *args):
            saved.append(args)

    monkeypatch.setattr("avito_studio.app.QSettings", FakeSettings)
    template = _bridge_root(tmp_path / "template")
    (template / "profiles").mkdir()
    (template / "profiles" / "wreaths.yaml").write_text(
        "profile: {name: wreaths}\n", encoding="utf-8"
    )
    target = tmp_path / "local-app-data" / "bridge"

    installed = ensure_bundled_workspace(template, target)
    assert installed == target.resolve()
    assert (installed / "profiles" / "wreaths.yaml").is_file()
    config = installed / "config" / "config.yaml"
    config.write_text("user: changed\n", encoding="utf-8")

    assert ensure_bundled_workspace(template, target) == installed
    assert config.read_text(encoding="utf-8") == "user: changed\n"
    assert saved == [
        ("bridge_root", str(installed)),
        ("bridge_root", str(installed)),
    ]


def test_bundled_workspace_can_upgrade_without_persisting_qsettings(
    tmp_path, monkeypatch
):
    class FailIfCreatedSettings:
        def __init__(self, *_args):
            raise AssertionError("QSettings must not be touched")

    monkeypatch.setattr("avito_studio.app.QSettings", FailIfCreatedSettings)
    template = _bridge_root(tmp_path / "template")
    target = tmp_path / "target"

    assert ensure_bundled_workspace(
        template,
        target,
        persist_setting=False,
    ) == target.resolve()


def test_bundled_workspace_rejects_missing_or_invalid_template(tmp_path):
    assert ensure_bundled_workspace(tmp_path / "missing", tmp_path / "target") is None
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    assert ensure_bundled_workspace(invalid, tmp_path / "target") is None


def test_connection_settings_environment_and_validation(monkeypatch, tmp_path):
    key = tmp_path / "id_test"
    key.write_text("private", encoding="utf-8")
    monkeypatch.setenv(SSH_HOST_ENV, "deploy@example.test")
    monkeypatch.setenv(SSH_KEY_ENV, str(key))

    assert connection_settings() == ("deploy@example.test", str(key))
    assert validate_connection_settings("deploy@example.test", str(key)) == (
        "deploy@example.test",
        str(key.resolve()),
    )


def test_connection_settings_has_no_production_host_default(monkeypatch):
    class EmptySettings:
        def __init__(self, *_args):
            pass

        @staticmethod
        def value(_key, default=""):
            return default

    monkeypatch.delenv(SSH_HOST_ENV, raising=False)
    monkeypatch.delenv(SSH_KEY_ENV, raising=False)
    monkeypatch.setattr("avito_studio.app.QSettings", EmptySettings)

    host, _key = connection_settings()

    assert host == ""


def test_connection_settings_reject_option_injection_and_missing_key(tmp_path):
    with pytest.raises(ValueError, match="безопасный"):
        validate_connection_settings("-oProxyCommand=bad", str(tmp_path / "key"))
    with pytest.raises(ValueError, match="не найден"):
        validate_connection_settings("root@example.test", str(tmp_path / "missing"))


def test_save_connection_settings_validates_and_persists(
    monkeypatch, tmp_path
):
    stored = {}

    class FakeSettings:
        def __init__(self, *_args):
            pass

        def setValue(self, key, value):
            stored[key] = value

    key = tmp_path / "id_test"
    key.write_text("private", encoding="utf-8")
    monkeypatch.setattr("avito_studio.app.QSettings", FakeSettings)

    assert save_connection_settings(" deploy@example.test ", str(key)) == (
        "deploy@example.test",
        str(key.resolve()),
    )
    assert stored == {
        "ssh_host": "deploy@example.test",
        "ssh_key": str(key.resolve()),
    }


def test_setup_connection_dialog_handles_cancel_validation_and_success(
    qtbot, monkeypatch, tmp_path
):
    ssh = type("Ssh", (), {"host": "root@old.test", "key_path": "old-key"})()
    window = BridgeSetupWindow(ssh)
    qtbot.addWidget(window)
    warnings = []
    information = []
    monkeypatch.setattr(
        "avito_studio.app.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )
    monkeypatch.setattr(
        "avito_studio.app.QMessageBox.information",
        lambda *args: information.append(args),
    )

    monkeypatch.setattr(
        "avito_studio.app.QInputDialog.getText",
        lambda *_args, **_kwargs: ("ignored", False),
    )
    window._configure_connection()
    assert warnings == []

    monkeypatch.setattr(
        "avito_studio.app.QInputDialog.getText",
        lambda *_args, **_kwargs: ("-oBad", True),
    )
    monkeypatch.setattr(
        "avito_studio.app.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    window._configure_connection()
    assert warnings == []

    key = tmp_path / "id_test"
    key.write_text("private", encoding="utf-8")
    monkeypatch.setattr(
        "avito_studio.app.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(key), ""),
    )
    window._configure_connection()
    assert "безопасный" in warnings[-1][2]

    monkeypatch.setattr(
        "avito_studio.app.QInputDialog.getText",
        lambda *_args, **_kwargs: ("deploy@example.test", True),
    )
    monkeypatch.setattr(
        "avito_studio.app.save_connection_settings",
        lambda host, path: (host, str(Path(path).resolve())),
    )
    window._configure_connection()
    assert ssh.host == "deploy@example.test"
    assert ssh.key_path == str(key.resolve())
    assert information[-1][1] == "Подключение сохранено"


def test_setup_bridge_picker_validates_selection_and_opens_nested_checkout(
    qtbot, monkeypatch, tmp_path
):
    ssh = _OfflineSsh()
    window = BridgeSetupWindow(ssh, tmp_path)
    qtbot.addWidget(window)
    warnings = []
    monkeypatch.setattr(
        "avito_studio.app.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )

    monkeypatch.setattr(
        "avito_studio.app.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "",
    )
    window._choose_bridge_root()
    assert window._main_window is None

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    monkeypatch.setattr(
        "avito_studio.app.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(invalid),
    )
    window._choose_bridge_root()
    assert "нет config/config.yaml" in warnings[-1][2]

    parent = tmp_path / "parent"
    nested = _bridge_root(parent / "avito-bridge")
    opened = {}

    class FakeMainWindow:
        def __init__(self, bridge_root, config_path, ssh):
            opened["args"] = (bridge_root, config_path, ssh)

        def resize(self, *size):
            opened["size"] = size

        def show(self):
            opened["shown"] = True

    class FakeSettings:
        def __init__(self, *_args):
            pass

        def setValue(self, key, value):
            opened["setting"] = (key, value)

    monkeypatch.setattr("avito_studio.app.MainWindow", FakeMainWindow)
    monkeypatch.setattr("avito_studio.app.QSettings", FakeSettings)
    monkeypatch.setattr(
        "avito_studio.app.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(parent),
    )
    window._choose_bridge_root()

    assert opened["args"] == (
        nested,
        nested / "config" / "config.yaml",
        ssh,
    )
    assert opened["size"] == (1360, 820)
    assert opened["shown"] is True


def test_setup_bridge_picker_reports_config_constructor_failure(
    qtbot, monkeypatch, tmp_path
):
    root = _bridge_root(tmp_path / "bridge")
    window = BridgeSetupWindow(_OfflineSsh())
    qtbot.addWidget(window)
    critical = []
    monkeypatch.setattr(
        "avito_studio.app.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(root),
    )
    monkeypatch.setattr(
        "avito_studio.app.MainWindow",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("bad schema")),
    )
    monkeypatch.setattr(
        "avito_studio.app.QSettings",
        lambda *_args: type(
            "Settings", (), {"setValue": lambda self, *_values: None}
        )(),
    )
    monkeypatch.setattr(
        "avito_studio.app.QMessageBox.critical",
        lambda *args: critical.append(args),
    )

    window._choose_bridge_root()

    assert window._main_window is None
    assert "bad schema" in critical[-1][2]


def test_frozen_startup_falls_back_when_bundle_is_not_present(
    qtbot, monkeypatch, tmp_path
):
    root = _bridge_root(tmp_path / "existing")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "avito_studio.app.ensure_bundled_workspace", lambda **_kwargs: None
    )
    monkeypatch.setattr("avito_studio.app.resolve_bridge_root", lambda: root)

    window = build_initial_window(ssh=_OfflineSsh())
    qtbot.addWidget(window)

    assert isinstance(window, MainWindow)


def test_initial_window_builds_configured_ssh_client(
    qtbot, monkeypatch, tmp_path
):
    root = _bridge_root(tmp_path / "bridge")
    created = {}

    class FakeSsh:
        def __init__(self, host, key_path):
            created["settings"] = (host, key_path)

    monkeypatch.setattr(
        "avito_studio.app.connection_settings",
        lambda: ("deploy@example.test", "C:/key"),
    )
    monkeypatch.setattr("avito_studio.app.SshClient", FakeSsh)

    window = build_initial_window(root)
    qtbot.addWidget(window)

    assert isinstance(window, MainWindow)
    assert created["settings"] == ("deploy@example.test", "C:/key")


def test_smoke_checks_exercise_safe_main_window_ui(qtbot, tmp_path):
    root = _bridge_root(tmp_path / "bridge")
    window = build_initial_window(root, _OfflineSsh())
    qtbot.addWidget(window)
    window.show()

    run_smoke_checks(window)

    assert window.pages.currentIndex() == 0
    assert window.search.text() == ""
    assert window._catalog_loaded is False


def test_smoke_checks_reject_setup_window(qtbot):
    window = BridgeSetupWindow(_OfflineSsh())
    qtbot.addWidget(window)
    window.show()

    with pytest.raises(RuntimeError, match="setup window"):
        run_smoke_checks(window)


def test_smoke_mode_runs_qt_loop_and_schedules_offline_exit(monkeypatch):
    captured = {}

    class FakeApplication:
        def __init__(self, argv):
            captured["argv"] = argv

        def quit(self):
            captured["quit"] = True

        def exec(self):
            return 0

    class FakeWindow:
        def resize(self, *args):
            captured["resize"] = args

        def show(self):
            captured["shown"] = True

    application = FakeApplication([])
    monkeypatch.setattr("avito_studio.app.QApplication", lambda argv: application)
    monkeypatch.setattr("avito_studio.app.MainWindow", FakeWindow)
    monkeypatch.setattr(
        "avito_studio.app.build_initial_window",
        lambda **kwargs: captured.update(build_kwargs=kwargs) or FakeWindow(),
    )
    monkeypatch.setattr("avito_studio.app.apply_theme", lambda app: None)
    monkeypatch.setattr(
        "avito_studio.app.configure_logging", lambda: "test-studio.log"
    )
    monkeypatch.setattr(
        "avito_studio.app.QTimer.singleShot",
        lambda delay, callback: captured.update(delay=delay, callback=callback),
    )

    assert main(["--smoke-test"]) == 0
    assert captured["shown"] is True
    assert captured["delay"] == 750
    assert callable(captured["callback"])
    assert captured["build_kwargs"] == {"persist_workspace_setting": False}
