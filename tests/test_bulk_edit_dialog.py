from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from avito_studio.bulk_edit_dialog import BulkEditDialog
from avito_studio.catalog_service import CatalogMember, CatalogRow
from avito_studio.local_config import LocalConfig


def _row(key, brand, series, *, selected, price=20000, cost=15000):
    return CatalogRow(
        key=key,
        source="supplier",
        brand=brand,
        series=series,
        sizes="—",
        stock_total=1,
        has_card=True,
        forced=False,
        selected=selected,
        members=(CatalogMember(f"{key}-1", price, cost, True, False),),
    )


def _cfg(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalog:\n"
        "  force_include: {}\n"
        "  selected_series:\n"
        "    - \"jet\"\n"
        "    - \"aura\"\n",
        encoding="utf-8",
    )
    return LocalConfig(path)


def _dialog(qtbot, tmp_path):
    rows = [
        _row("jet", "XIGMA", "JETPRO", selected=True),
        _row("aura", "Ballu", "Aura", selected=True, price=30000),
        _row("other", "Funai", "Sensei", selected=False),
    ]
    dialog = BulkEditDialog(rows, _cfg(tmp_path))
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_lists_current_profile_rows_and_starts_with_empty_selection(qtbot, tmp_path):
    dialog = _dialog(qtbot, tmp_path)

    assert dialog.products_table.rowCount() == 3
    assert dialog.products_table.item(0, 1).text() == "XIGMA"
    assert dialog.selected_keys() == ()
    assert dialog.apply_btn.isEnabled() is False


def test_search_can_accumulate_targets_and_select_published_rows(qtbot, tmp_path):
    dialog = _dialog(qtbot, tmp_path)

    dialog.search_input.setText("JETPRO")
    dialog.select_filtered_btn.click()
    dialog.search_input.setText("Aura")
    dialog.select_filtered_btn.click()
    assert set(dialog.selected_keys()) == {"jet", "aura"}

    dialog.clear_selection_btn.click()
    dialog.search_input.clear()
    dialog.select_published_btn.click()
    assert set(dialog.selected_keys()) == {"jet", "aura"}


def test_percent_preview_shows_each_price_and_floor_skip(qtbot, tmp_path):
    dialog = _dialog(qtbot, tmp_path)
    dialog.products_table.item(0, 0).setCheckState(Qt.Checked)
    dialog.products_table.item(1, 0).setCheckState(Qt.Checked)
    dialog.price_mode_combo.setCurrentIndex(dialog.price_mode_combo.findData("percent"))
    dialog.price_value_input.setValue(-5)

    assert dialog.apply_btn.isEnabled() is True
    assert dialog.preview.price_changes[0].new_price == 19000
    assert "2" in dialog.preview_label.text()
    assert dialog.preview_table.rowCount() == 2


def test_local_apply_persists_preview_and_emits_result(qtbot, tmp_path, monkeypatch):
    dialog = _dialog(qtbot, tmp_path)
    dialog.products_table.item(0, 0).setCheckState(Qt.Checked)
    dialog.publication_combo.setCurrentIndex(dialog.publication_combo.findData("off"))
    emitted = []
    dialog.applied.connect(emitted.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.Yes),
    )

    dialog.apply_btn.click()

    assert len(emitted) == 1
    assert dialog.local_cfg.is_selected("jet") is False
    assert dialog.result() == QDialog.Accepted


def test_cancelled_confirmation_does_not_change_yaml(qtbot, tmp_path, monkeypatch):
    dialog = _dialog(qtbot, tmp_path)
    dialog.products_table.item(0, 0).setCheckState(Qt.Checked)
    dialog.publication_combo.setCurrentIndex(dialog.publication_combo.findData("off"))
    before = dialog.local_cfg.path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.No),
    )

    dialog.apply_btn.click()

    assert dialog.local_cfg.path.read_text(encoding="utf-8") == before
    assert dialog.result() == 0
