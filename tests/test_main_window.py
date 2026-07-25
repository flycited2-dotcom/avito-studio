import threading

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from avito_studio.bulk_changes import BulkPreview, MemberPriceChange, SeriesChange
from avito_studio.catalog_cache import save_catalog_cache
from avito_studio.catalog_service import CatalogRow
from avito_studio.main_window import MainWindow
from avito_studio.profiles import PROFILES

ROWS = [CatalogRow(key="a", source="breeze", brand="Funai", series="Sensei", sizes="7 тыс. BTU",
                   stock_total=2, has_card=True, forced=False, selected=False)]


class FakeSsh:
    def run(self, cmd):
        import json
        return json.dumps({"generated_at": "x", "series": [
            {"key": "a", "source": "breeze", "brand": "Funai", "series": "Sensei",
             "category_id": 2, "stock_total": 2, "has_card": True, "forced": False,
             "members": [{"nc_code": "1", "btu_calc": 7, "stock": 2, "price": 100,
                         "price_ok": True, "forced": False}]},
            {"key": "b", "source": "daichi", "brand": "Midea", "series": "Изи",
             "category_id": 2, "stock_total": 1, "has_card": False, "forced": False,
             "members": [{"nc_code": "2", "btu_calc": 9, "stock": 1, "price": 200,
                         "price_ok": True, "forced": False}]}]})

    def put(self, remote_path, data):
        pass


def test_refresh_populates_table_synchronously(qtbot, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    assert win.model.rowCount() == 2
    assert win.model.rows[0].brand == "Funai"


def test_dashboard_updates_counts_and_navigation(qtbot, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    assert win.pages.currentIndex() == 0
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    assert win.stat_total_value.text() == "2"
    assert win.stat_selected_value.text() == "2"  # пустой whitelist = публиковать всё
    assert win.stat_cards_value.text() == "1"
    assert win.stat_issues_value.text() == "1"
    win.nav_catalog.click()
    assert win.pages.currentIndex() == 1
    assert win.page_title.text() == "Каталог"
    assert win.nav_catalog.isChecked()


def test_about_dialog_reports_release_and_bridge_revision(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    shown = {}
    monkeypatch.setattr(
        QMessageBox,
        "about",
        staticmethod(
            lambda _parent, title, text: shown.update(title=title, text=text)
        ),
    )

    win._show_about()

    assert shown["title"] == "О программе"
    assert "Avito Content Studio 0.3.0" in shown["text"]
    assert "Avito Bridge:" in shown["text"]
    assert "studio.log" in shown["text"]


def test_toggle_checkbox_marks_dirty_and_updates_local_config(qtbot, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        'catalog:\n  selected_series: ["__none__"]\n', encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    idx = win.model.index(0, win.model.COL_SELECTED)
    win.model.setData(idx, Qt.Checked, Qt.CheckStateRole)
    win.save_local_selection()
    reloaded_text = cfg_path.read_text(encoding="utf-8")
    assert '"a"' in reloaded_text


def test_unchecking_one_from_implicit_all_saves_every_other_row(
    qtbot, tmp_path
):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    assert all(row.selected for row in win.model.rows)

    first = win.model.index(0, win.model.COL_SELECTED)
    win.model.setData(first, Qt.Unchecked, Qt.CheckStateRole)
    win.save_local_selection()

    assert not win.local_cfg.is_selected("a")
    assert win.local_cfg.is_selected("b")
    assert win.local_cfg.selected_series() == ["b"]


def test_saving_before_first_refresh_does_not_erase_existing_selection(
    qtbot, tmp_path
):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        'catalog:\n  selected_series: ["keep-me"]\n', encoding="utf-8"
    )
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)

    win.save_local_selection()

    assert win.local_cfg.selected_series() == ["keep-me"]


def test_refresh_saves_pending_checkbox_changes(qtbot, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh())
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    win.model.setData(
        win.model.index(0, win.model.COL_SELECTED),
        Qt.Unchecked,
        Qt.CheckStateRole,
    )

    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()

    assert win.local_cfg.selected_series() == ["b"]
    assert not win.model.rows[0].selected
    assert win.model.rows[1].selected


def _win(qtbot, tmp_path, catalog_yaml="catalog:\n  force_include: {}\n  manual_photos: {}\n  selected_series: []\n"):
    # deploy_and_rebuild() тарит bridge_root/config и bridge_root/avito-descriptions — обе папки
    # должны реально существовать, иначе tarfile падает на отсутствующем пути.
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "avito-descriptions").mkdir(exist_ok=True)
    cfg_path = tmp_path / "config" / "config.yaml"
    cfg_path.write_text(catalog_yaml, encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=cfg_path, ssh=FakeSsh(),
                     snapshot_dir=tmp_path / "publish-snapshot")   # не трогаем реальный ~/.avito-studio
    qtbot.addWidget(win)
    return win


def test_add_forced_dialog_shows_confirmation_on_success(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    from avito_studio.add_forced_dialog import AddForcedProductDialog
    monkeypatch.setattr(AddForcedProductDialog, "exec", lambda self: 1)
    monkeypatch.setattr(AddForcedProductDialog, "save", lambda self: None)
    shown = {"info": False}
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.update(info=True)))
    win._open_add_forced_dialog()
    assert shown["info"] is True


def test_add_forced_dialog_shows_error_on_save_failure(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    from avito_studio.add_forced_dialog import AddForcedProductDialog
    monkeypatch.setattr(AddForcedProductDialog, "exec", lambda self: 1)

    def boom(self):
        raise RuntimeError("network error")
    monkeypatch.setattr(AddForcedProductDialog, "save", boom)
    shown = {"error": False}
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.update(error=True)))
    win._open_add_forced_dialog()   # не должно упасть необработанным исключением
    assert shown["error"] is True


def test_edit_dialog_shows_confirmation_on_success(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    from avito_studio.edit_dialog import EditSeriesDialog
    monkeypatch.setattr(EditSeriesDialog, "exec", lambda self: 1)
    monkeypatch.setattr(EditSeriesDialog, "save", lambda self: None)
    shown = {"info": False}
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.update(info=True)))
    win._open_edit_dialog(win.proxy.index(0, 0))
    assert shown["info"] is True


def test_edit_dialog_shows_error_on_save_failure(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    from avito_studio.edit_dialog import EditSeriesDialog
    monkeypatch.setattr(EditSeriesDialog, "exec", lambda self: 1)

    def boom(self):
        raise RuntimeError("upload failed")
    monkeypatch.setattr(EditSeriesDialog, "save", boom)
    shown = {"error": False}
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.update(error=True)))
    win._open_edit_dialog(win.proxy.index(0, 0))   # не должно упасть необработанным исключением
    assert shown["error"] is True


def test_publish_does_not_deploy_when_confirmation_declined(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    win.publish()
    assert win._threads == []


def test_carver_profile_shows_readiness_check_before_publish(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win.profile = next(p for p in PROFILES if p.key == "carver")
    win._set_busy(False)
    shown = {"warning": False}
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: shown.update(warning=True)))
    win.publish()
    assert shown["warning"] is True
    assert win._threads == []
    assert win.act_publish.isEnabled()
    assert win.act_import_cards.isEnabled()
    assert win.act_import_cards.text() == "Взять фото из прайса"


def test_carver_settings_action_is_only_visible_for_carver(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    assert not win.act_carver_settings.isVisible()
    win.profile = next(p for p in PROFILES if p.key == "carver")
    win._set_busy(False)
    assert win.act_carver_settings.isVisible()
    assert win.act_carver_settings.isEnabled()


def test_bulk_action_is_available_for_every_profile_and_has_shortcut(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    for profile in PROFILES:
        win.profile = profile
        win._set_busy(False)
        assert win.act_bulk_edit.isVisible()
        assert win.act_bulk_edit.isEnabled()
    assert win.act_bulk_edit.shortcut().toString() == "Ctrl+Shift+B"


def test_bulk_dialog_result_updates_catalog_without_deploy(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path, catalog_yaml=(
        "catalog:\n"
        "  force_include: {}\n"
        "  manual_photos: {}\n"
        "  selected_series:\n"
        "    - \"a\"\n"
    ))
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    from avito_studio.bulk_edit_dialog import BulkEditDialog

    preview = BulkPreview(
        series_changes=(SeriesChange("a", True, False),),
        price_changes=(MemberPriceChange("a", "1", 100, 95, False),),
    )

    def emit_preview(dialog):
        dialog.applied.emit(preview)
        return 1

    monkeypatch.setattr(BulkEditDialog, "exec", emit_preview)
    thread_count = len(win._threads)

    win._open_bulk_edit_dialog()

    assert win.model.rows[0].selected is False
    assert win.model.rows[0].price_range == "95 ₽"
    assert win.stat_selected_value.text() == "0"
    assert len(win._threads) == thread_count


def test_publish_deploys_when_confirmed(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    with qtbot.waitSignal(win.deploy_done, timeout=3000):
        win.publish()
    qtbot.waitUntil(lambda: not win._threads, timeout=3000)


def test_publish_confirmation_lists_concrete_changes_after_first_publish(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    with qtbot.waitSignal(win.deploy_done, timeout=3000):
        win.publish()                        # первая публикация — снапшот записан
    win.local_cfg.set_manual_price("НС-7", 19990)
    win.local_cfg.save()
    asked = {}

    def capture_question(parent, title, text, *a, **k):
        asked["text"] = text
        return QMessageBox.No               # только смотрим сводку, не публикуем
    monkeypatch.setattr(QMessageBox, "question", staticmethod(capture_question))
    win.publish()
    assert "НС-7" in asked["text"] and "19990" in asked["text"]


def test_publish_saves_snapshot_for_next_summary(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    with qtbot.waitSignal(win.deploy_done, timeout=3000):
        win.publish()
    assert (
        tmp_path
        / "publish-snapshot"
        / "conditioners"
        / "config"
        / "config.yaml"
    ).exists()


def test_busy_guard_disables_and_reenables_toolbar_actions(qtbot, tmp_path):
    # двойной клик по «Опубликовать» не должен запускать два параллельных деплоя
    win = _win(qtbot, tmp_path)
    win._set_busy(True)
    assert all(not a.isEnabled() for a in win._busy_actions)
    win._set_busy(False)
    assert all(a.isEnabled() for a in win._busy_actions)


def test_publish_reenables_actions_after_success(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    with qtbot.waitSignal(win.deploy_done, timeout=3000):
        win.publish()
    assert all(a.isEnabled() for a in win._busy_actions)


WREATHS_JSON_SERIES = [
    {"key": "ritualb2b|item|ritualb2b:w-1", "source": "ritualb2b", "brand": "",
     "series": "Венок «Аврора»", "category_id": 0, "stock_total": 3, "has_card": False,
     "forced": False, "members": [{"nc_code": "w-1", "btu_calc": None, "stock": 3,
                                   "price": 2300, "price_ok": True, "forced": False}]},
]


class ProfileAwareSsh(FakeSsh):
    """Возвращает венки для --config profiles/wreaths.yaml, иначе кондиционеры."""

    def __init__(self):
        self.calls = []

    def run(self, cmd):
        import json
        self.calls.append(cmd)
        if "profiles/wreaths.yaml" in cmd:
            return json.dumps({"generated_at": "x", "series": WREATHS_JSON_SERIES})
        return super().run(cmd)


def _win_with_wreaths_profile(qtbot, tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "avito-descriptions").mkdir(exist_ok=True)
    (tmp_path / "profiles").mkdir(exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(
        'catalog:\n  force_include: {}\n  manual_photos: {}\n'
        '  selected_series: ["__none__"]\n', encoding="utf-8")
    (tmp_path / "profiles" / "wreaths.yaml").write_text(
        "catalog:\n  selected_series: []\n", encoding="utf-8")
    win = MainWindow(bridge_root=tmp_path, config_path=tmp_path / "config" / "config.yaml",
                     ssh=ProfileAwareSsh(), snapshot_dir=tmp_path / "publish-snapshot")
    qtbot.addWidget(win)
    return win


def test_profile_selector_switches_catalog_and_local_config(qtbot, tmp_path):
    win = _win_with_wreaths_profile(qtbot, tmp_path)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    assert win.model.rows[0].brand == "Funai"              # стартовый профиль — кондиционеры
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win._switch_profile(1)                             # «Венки»
    assert win.profile_combo.currentIndex() == 1
    assert [r.series for r in win.model.rows] == ["Венок «Аврора»"]
    assert win.local_cfg.path == tmp_path / "profiles" / "wreaths.yaml"
    assert "--config profiles/wreaths.yaml" in win.ssh.calls[-1]


def test_profile_switch_saves_pending_selection_of_previous_profile(qtbot, tmp_path):
    # несохранённые галочки кондиционеров не должны молча пропасть при уходе на венки
    win = _win_with_wreaths_profile(qtbot, tmp_path)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    idx = win.model.index(0, win.model.COL_SELECTED)
    win.model.setData(idx, Qt.Checked, Qt.CheckStateRole)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win._switch_profile(1)
    assert '"a"' in (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")


def test_profile_selector_reverts_when_profile_config_missing(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)                            # profiles/wreaths.yaml НЕ создан
    shown = {"error": False}
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.update(error=True)))
    win._switch_profile(1)
    assert shown["error"] is True
    assert win.profile.key == "conditioners"               # остались на кондиционерах
    assert win.profile_combo.currentIndex() == 0


def test_profile_selector_stays_put_when_pending_selection_cannot_be_saved(
    qtbot, tmp_path, monkeypatch
):
    win = _win_with_wreaths_profile(qtbot, tmp_path)
    shown = {"error": False}

    def fail_save():
        raise OSError("disk is read-only")

    monkeypatch.setattr(win, "save_local_selection", fail_save)
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: shown.update(error=True)),
    )

    win._switch_profile(1)

    assert shown["error"] is True
    assert win.profile.key == "conditioners"
    assert win.profile_combo.currentIndex() == 0


def test_profile_switch_clears_stale_rows_and_hides_btu_column(qtbot, tmp_path, monkeypatch):
    win = _win_with_wreaths_profile(qtbot, tmp_path)
    win.model = win.model.__class__(ROWS)
    win.proxy.setSourceModel(win.model)
    monkeypatch.setattr(win, "refresh", lambda: None)

    win._switch_profile(1)

    assert win.profile.key == "wreaths"
    assert win.model.rowCount() == 0
    assert win.model.headerData(win.model.COL_SERIES, Qt.Horizontal) == "Товар"
    assert win.table.isColumnHidden(win.model.COL_SIZES)


def test_carver_profile_waits_for_explicit_price_import(qtbot, tmp_path):
    win = _win_with_wreaths_profile(qtbot, tmp_path)
    (tmp_path / "profiles" / "carver.yaml").write_text(
        "profile:\n"
        "  source_options:\n"
        '    path: "runtime/carver/current.xlsx"\n'
        "catalog:\n"
        "  selected_series: []\n",
        encoding="utf-8",
    )
    calls_before = list(win.ssh.calls)

    win._switch_profile(3)

    assert win.profile.key == "carver"
    assert win._threads == []
    assert win.ssh.calls == calls_before
    assert "выберите свежий XLSX-прайс CARVER" in win.statusBar().currentMessage()


def test_add_dialog_receives_active_profile(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win.profile = PROFILES[3]
    from avito_studio.add_forced_dialog import AddForcedProductDialog
    captured = {}
    real_init = AddForcedProductDialog.__init__

    def spy_init(self, local_cfg, ssh, profile=PROFILES[0], parent=None):
        captured["profile"] = profile
        real_init(self, local_cfg, ssh, profile=profile, parent=parent)

    monkeypatch.setattr(AddForcedProductDialog, "__init__", spy_init)
    monkeypatch.setattr(AddForcedProductDialog, "exec", lambda self: 0)

    win._open_add_forced_dialog()

    assert captured["profile"].key == "carver"


def test_profile_combo_disabled_while_busy(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._set_busy(True)
    assert not win.profile_combo.isEnabled()
    win._set_busy(False)
    assert win.profile_combo.isEnabled()


def test_edit_dialog_opens_correct_row_with_filter_and_sort(qtbot, tmp_path, monkeypatch):
    # фильтр + сортировка меняют порядок строк в ПРОКСИ; двойной клик обязан открывать
    # именно ту серию, по которой кликнули (mapToSource), а не строку с тем же номером в модели
    win = _win(qtbot, tmp_path)
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    win.search.setText("Midea")           # в прокси остаётся одна строка (в модели она вторая)
    assert win.proxy.rowCount() == 1
    from avito_studio.edit_dialog import EditSeriesDialog
    opened = {}
    real_init = EditSeriesDialog.__init__

    def spy_init(self, row, *a, **k):
        opened["row"] = row
        real_init(self, row, *a, **k)
        qtbot.addWidget(self)   # иначе окно-сирота может уронить teardown интерпретатора
    monkeypatch.setattr(EditSeriesDialog, "__init__", spy_init)
    monkeypatch.setattr(EditSeriesDialog, "exec", lambda self: 0)   # сразу «Отмена»
    win._open_edit_dialog(win.proxy.index(0, 0))
    assert opened["row"].brand == "Midea"


def test_publish_failure_shows_critical_box_and_reenables(qtbot, tmp_path, monkeypatch):
    # провал публикации — денежный путь: пользователь ОБЯЗАН увидеть модальную ошибку,
    # а не пропустить 10-секундную строку в статус-баре и думать, что всё ушло на Avito
    win = _win(qtbot, tmp_path)

    def boom(remote_path, data):
        raise RuntimeError("No space left on device")
    win.ssh.put = boom
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    shown = {"error": False}
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.update(error=True)))
    with qtbot.waitSignal(win.publish_failed, timeout=3000):
        win.publish()
    assert shown["error"] is True
    assert all(a.isEnabled() for a in win._busy_actions)


def test_appliances_content_import_runs_outside_ui_thread(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path)
    win.profile = next(profile for profile in PROFILES if profile.key == "appliances")
    row = CatalogRow(
        key="price_xls|item|pricexls:UT-1",
        source="price_xls",
        brand="Ballu",
        series="Водонагреватель Ballu BWH/S 80 Shell",
        sizes="—",
        stock_total=1,
        has_card=False,
        forced=False,
        selected=False,
        representative_nc="UT-1",
    )
    win._install_catalog_model([row])
    win._set_busy(False)
    observed = {}

    def fake_import(ssh, rows, local_cfg):
        observed["thread"] = QThread.currentThread()
        return 1, 1, 0

    import avito_studio.content_card_import as importer
    monkeypatch.setattr(importer, "import_content_cards", fake_import)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    win._import_content_cards()
    qtbot.waitUntil(lambda: not win._threads, timeout=3000)

    assert observed["thread"] is not win.thread()
    assert all(
        action.isEnabled()
        for action in win._busy_actions
        if action is not win.act_publish
    )
    assert win.act_publish.isEnabled() is False


class _BlockingWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, gate):
        super().__init__()
        self.gate = gate

    def run(self):
        self.gate.wait(3)
        self.finished.emit("done")


def test_close_waits_for_worker_and_thread_registry_is_pruned(
    qtbot, tmp_path, monkeypatch
):
    win = _win(qtbot, tmp_path)
    gate = threading.Event()
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    win._start_worker(_BlockingWorker(gate), lambda _result: None, lambda _error: None)
    qtbot.waitUntil(lambda: bool(win._running_threads()), timeout=1000)

    event = QCloseEvent()
    win.closeEvent(event)

    assert not event.isAccepted()
    assert win._close_when_idle is True
    assert len(win._threads) == 1

    gate.set()
    qtbot.waitUntil(lambda: not win._threads, timeout=3000)


class _UnavailableCatalogSsh:
    def run(self, _command):
        raise RuntimeError("SSH: connection timed out")


def test_cached_catalog_is_prominent_read_only_and_blocks_publish(
    qtbot, tmp_path, monkeypatch
):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    save_catalog_cache(
        "conditioners",
        [
            CatalogRow(
                key="cached-row",
                source="breeze",
                brand="Funai",
                series="Снимок",
                sizes="7 тыс. BTU",
                stock_total=1,
                has_card=True,
                forced=False,
                selected=False,
            )
        ],
    )
    win = MainWindow(
        bridge_root=tmp_path,
        config_path=cfg_path,
        ssh=_UnavailableCatalogSsh(),
    )
    qtbot.addWidget(win)

    with qtbot.waitSignal(win.refresh_stale, timeout=3000) as blocker:
        win.refresh()
    qtbot.waitUntil(lambda: not win._threads, timeout=3000)

    assert "connection timed out" in blocker.args[0]
    assert win.model.rowCount() == 1
    assert win.model.rows[0].selected is True
    assert win._catalog_loaded is False
    assert win._catalog_stale is True
    assert not win.cache_warning.isHidden()
    assert "КЭШ — ДАННЫЕ НЕ АКТУАЛЬНЫ" in win.cache_warning.text()
    assert "КЭШ / НЕ АКТУАЛЬНО" in win.statusBar().currentMessage()
    assert win.statusBar().property("error") is True
    assert win.table.isEnabled()
    selected_index = win.model.index(0, win.model.COL_SELECTED)
    assert not (win.model.flags(selected_index) & Qt.ItemIsUserCheckable)
    assert (
        win.model.setData(selected_index, Qt.Unchecked, Qt.CheckStateRole)
        is False
    )
    assert win.model.rows[0].selected is True
    assert win.search.isEnabled()
    assert win.act_refresh.isEnabled()
    assert not win.act_publish.isEnabled()
    assert not win.act_add.isEnabled()
    assert not win.act_status.isEnabled()
    assert not win.act_bulk_edit.isEnabled()

    shown = {}
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(
            lambda _parent, title, text: shown.update(title=title, text=text)
        ),
    )
    win.publish()
    assert shown["title"] == "Публикация заблокирована"
    assert win._threads == []


def test_fresh_refresh_leaves_cache_mode_and_reenables_catalog(qtbot, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    cached = CatalogRow(
        key="cached-row",
        source="breeze",
        brand="Funai",
        series="Снимок",
        sizes="—",
        stock_total=1,
        has_card=False,
        forced=False,
        selected=True,
    )
    save_catalog_cache("conditioners", [cached])
    win = MainWindow(
        bridge_root=tmp_path,
        config_path=cfg_path,
        ssh=_UnavailableCatalogSsh(),
    )
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.refresh_stale, timeout=3000):
        win.refresh()
    qtbot.waitUntil(lambda: not win._threads, timeout=3000)

    win.ssh = FakeSsh()
    with qtbot.waitSignal(win.refresh_done, timeout=3000):
        win.refresh()
    qtbot.waitUntil(lambda: not win._threads, timeout=3000)

    assert win._catalog_stale is False
    assert win._catalog_loaded is True
    assert win.cache_warning.isHidden()
    assert win.table.isEnabled()
    assert win.act_publish.isEnabled()
    assert "КЭШ" not in win.statusBar().currentMessage()
