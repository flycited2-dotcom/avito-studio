from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from avito_studio.main_window import MainWindow
from avito_studio.profiles import PROFILES


class NoExternalSsh:
    def run(self, _command):
        raise AssertionError("Импорт XLS не должен обращаться к SSH")

    def put(self, _remote_path, _data):
        raise AssertionError("Импорт XLS не должен отправлять файлы")


def _window(qtbot, tmp_path: Path, source_path: str = "missing-old.xls"):
    bridge_root = tmp_path / "bridge"
    config_path = bridge_root / "profiles" / "appliances.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "profile:\n"
        "  name: appliances\n"
        "  source_options:\n"
        f'    path: "{source_path}"\n'
        "catalog:\n"
        "  selected_series: []\n",
        encoding="utf-8",
    )
    window = MainWindow(
        bridge_root,
        config_path,
        NoExternalSsh(),
        snapshot_dir=tmp_path / "snapshots",
    )
    window.profile = next(profile for profile in PROFILES if profile.key == "appliances")
    window._set_busy(False)
    qtbot.addWidget(window)
    return window


def test_price_import_action_is_only_available_for_appliances(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    assert window.act_appliances_price.isVisible()
    assert window.act_appliances_price.isEnabled()
    assert not window.appliances_price_card.isHidden()

    window.profile = next(profile for profile in PROFILES if profile.key == "carver")
    window._set_busy(False)
    assert not window.act_appliances_price.isVisible()
    assert not window.act_appliances_price.isEnabled()
    assert window.appliances_price_card.isHidden()


def test_cancelled_picker_does_not_probe_or_change_missing_absolute_source(
    qtbot, tmp_path, monkeypatch
):
    missing = "Z:/removed-machine/private/priceopt.xls"
    window = _window(qtbot, tmp_path, missing)
    observed = {}

    def cancel(_parent, _caption, directory, _filter):
        observed["directory"] = directory
        return "", ""

    from avito_studio import ui_components

    monkeypatch.setattr(ui_components, "get_open_file_name", cancel)
    window._open_appliances_price_import()

    assert observed["directory"] == ""
    assert window.local_cfg.get_source_path() == missing
    assert window._threads == []


def test_switch_to_appliances_does_not_refresh_missing_legacy_absolute_path(
    qtbot, tmp_path
):
    missing = "Z:/removed-machine/private/priceopt.xls"
    window = _window(qtbot, tmp_path, missing)
    window.profile = PROFILES[0]
    window.profile_combo.setCurrentIndex(0)
    window._set_busy(False)
    appliances_index = next(
        index
        for index, profile in enumerate(PROFILES)
        if profile.key == "appliances"
    )

    window._switch_profile(appliances_index)

    assert window.profile.key == "appliances"
    assert window._threads == []
    assert "Импортировать XLS-прайс" in window.statusBar().currentMessage()
    assert window.local_cfg.get_source_path() == missing


def test_price_import_runs_in_worker_and_never_publishes(
    qtbot, tmp_path, monkeypatch
):
    window = _window(qtbot, tmp_path)
    selected = tmp_path / "chosen.xls"
    selected.write_bytes(b"fixture handled by stub")
    observed = {}

    from avito_studio import appliances_price_file, ui_components

    monkeypatch.setattr(
        ui_components,
        "get_open_file_name",
        lambda *_args: (str(selected), "Прайс Excel 97–2003 (*.xls)"),
    )

    def fake_import(source, bridge_root, local_cfg):
        observed["thread"] = QThread.currentThread()
        observed["source"] = source
        observed["bridge_root"] = bridge_root
        observed["local_cfg"] = local_cfg
        return bridge_root / "runtime" / "appliances" / "current.xls", 1626

    monkeypatch.setattr(
        appliances_price_file, "import_appliances_price", fake_import
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_a, **_k: None))

    with qtbot.waitSignal(window.appliances_price_import_done, timeout=3000) as blocker:
        window._open_appliances_price_import()
    qtbot.waitUntil(lambda: not window._threads, timeout=3000)

    assert blocker.args[1] == 1626
    assert observed["thread"] is not window.thread()
    assert observed["source"] == selected
    assert observed["bridge_root"] == window.bridge_root
    assert observed["local_cfg"] is window.local_cfg
    assert "ничего не отправлено" not in window.statusBar().currentMessage()
    assert window.act_appliances_price.isEnabled()


def test_price_import_error_is_explicit_and_keeps_action_available(
    qtbot, tmp_path, monkeypatch
):
    window = _window(qtbot, tmp_path)
    selected = tmp_path / "wrong.xls"
    selected.write_bytes(b"wrong")
    messages = []

    from avito_studio import appliances_price_file, ui_components

    monkeypatch.setattr(
        ui_components, "get_open_file_name", lambda *_args: (str(selected), "")
    )
    monkeypatch.setattr(
        appliances_price_file,
        "import_appliances_price",
        lambda *_args: (_ for _ in ()).throw(
            ValueError("Неверная структура XLS-прайса")
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, title, text: messages.append((title, text))),
    )

    window._open_appliances_price_import()
    qtbot.waitUntil(lambda: bool(messages) and not window._threads, timeout=3000)

    assert messages[0][0] == "Прайс не импортирован"
    assert "Неверная структура" in messages[0][1]
    assert "Старый локальный прайс" in messages[0][1]
    assert window.act_appliances_price.isEnabled()
