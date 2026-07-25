import os
import time

import pytest
from PySide6.QtWidgets import QMessageBox

from avito_studio import carver_price_file
from avito_studio import carver_publish_settings_dialog as settings_dialog
from avito_studio.carver_publish_settings_dialog import CarverPublishSettingsDialog
from avito_studio.carver_readiness import carver_publish_issues
from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig


def _config(path):
    path.write_text(
        "pricing:\n"
        "  rounding: none\n"
        "  default_markup_pct: 0\n"
        "  min_margin_abs: 0\n"
        "  rules: []\n"
        "profile:\n"
        "  source_options:\n"
        "    path: ''\n"
        "feed:\n"
        "  base_tags:\n"
        "    AdType: 'Товар приобретен на продажу'\n"
        "    Condition: 'Новое'\n"
        "  product_type_default: ''\n"
        "catalog:\n"
        "  selected_series: []\n"
        "  manual_photos: {}\n",
        encoding="utf-8",
    )


def test_carver_settings_dialog_saves_category_and_markup(qtbot, tmp_path):
    path = tmp_path / "bridge" / "profiles" / "carver.yaml"
    path.parent.mkdir(parents=True)
    _config(path)
    local_cfg = LocalConfig(path)
    dlg = CarverPublishSettingsDialog(local_cfg)
    qtbot.addWidget(dlg)
    dlg.category_input.setText("Для дома и дачи")
    dlg.goods_type_input.setText("Садовая техника")
    dlg.goods_subtype_input.setText("Генераторы")
    current = tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"current")
    dlg.price_path_input.setText("runtime/carver/current.xlsx")
    dlg.markup_input.setValue(12.5)
    dlg.rounding_combo.setCurrentIndex(dlg.rounding_combo.findData("up_to_90"))
    dlg.save()

    saved = LocalConfig(path).get_publication_settings()
    assert saved == {
        "category": "Для дома и дачи",
        "goods_type": "Садовая техника",
        "goods_subtype": "Генераторы",
        "markup_pct": 12.5,
        "rounding": "up_to_90",
        "price_confirmed": False,
    }
    assert LocalConfig(path).get_source_path() == "runtime/carver/current.xlsx"


def test_carver_zero_markup_can_be_explicitly_confirmed(qtbot, tmp_path):
    path = tmp_path / "bridge" / "profiles" / "carver.yaml"
    path.parent.mkdir(parents=True)
    _config(path)
    local_cfg = LocalConfig(path)
    dlg = CarverPublishSettingsDialog(local_cfg)
    qtbot.addWidget(dlg)
    dlg.category_input.setText("Для дома и дачи")
    dlg.goods_type_input.setText("Садовая техника")
    dlg.markup_input.setValue(0)
    dlg.price_confirmed.setChecked(True)
    current = tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"current")
    dlg.price_path_input.setText("runtime/carver/current.xlsx")
    dlg.save()

    row = CatalogRow(
        key="carver_xlsx|item|carver:PPG-1900IS", source="carver_xlsx", brand="CARVER",
        series="Генератор CARVER PPG-1900IS", sizes="—", stock_total=1,
        has_card=True, forced=False, selected=True,
    )
    assert carver_publish_issues(path, [row]) == []


def test_carver_publish_is_blocked_when_installed_price_is_stale(tmp_path):
    path = tmp_path / "bridge" / "profiles" / "carver.yaml"
    path.parent.mkdir(parents=True)
    _config(path)
    cfg = LocalConfig(path)
    cfg.set_publication_settings(
        category="Для дома и дачи",
        goods_type="Садовая техника",
        goods_subtype="Генераторы",
        markup_pct=10,
        rounding="none",
        price_confirmed=False,
    )
    current = tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"stale")
    cfg.set_source_path(current, relative_to=tmp_path / "bridge")
    cfg.save()
    old = time.time() - (
        carver_price_file.MAX_PRICE_AGE_DAYS + 1
    ) * 24 * 60 * 60
    os.utime(current, (old, old))
    row = CatalogRow(
        key="carver_xlsx|item|carver:PPG-1900IS",
        source="carver_xlsx",
        brand="CARVER",
        series="Генератор CARVER PPG-1900IS",
        sizes="—",
        stock_total=1,
        has_card=True,
        forced=False,
        selected=True,
        representative_nc="PPG-1900IS",
    )

    issues = carver_publish_issues(path, [row])

    assert any("старше 90 дней" in issue for issue in issues)
    assert any("Выберите свежий файл" in issue for issue in issues)


def _mock_price(monkeypatch, count=24):
    rows = [
        {
            "row": index + 4,
            "article": f"PPG-{index}",
            "model": f"PPG-{index}",
            "name": f"Генератор {index}",
            "price": 10_000 + index,
            "kind": "generator",
        }
        for index in range(count)
    ]
    monkeypatch.setattr(carver_price_file, "parse_carver_xlsx", lambda path: rows)
    monkeypatch.setattr(
        carver_price_file,
        "extract_embedded_photos",
        lambda path: {row["article"]: b"photo" for row in rows},
    )


def _dialog_with_runtime(qtbot, tmp_path):
    bridge_root = tmp_path / "bridge"
    config_path = bridge_root / "profiles" / "carver.yaml"
    config_path.parent.mkdir(parents=True)
    _config(config_path)
    current = bridge_root / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"last-good")
    dialog = CarverPublishSettingsDialog(LocalConfig(config_path))
    qtbot.addWidget(dialog)
    return dialog, config_path, current


def test_choosing_price_and_cancelling_does_not_replace_current(
        qtbot, tmp_path, monkeypatch):
    dialog, _config_path, current = _dialog_with_runtime(qtbot, tmp_path)
    candidate = tmp_path / "supplier.xlsx"
    candidate.write_bytes(b"candidate")
    _mock_price(monkeypatch)
    monkeypatch.setattr(
        settings_dialog,
        "get_open_file_name",
        lambda *args, **kwargs: (str(candidate), "Excel (*.xlsx)"),
    )

    dialog._choose_price_file()

    assert dialog.price_path_input.text() == str(candidate.resolve())
    assert current.read_bytes() == b"last-good"
    dialog.reject()
    assert current.read_bytes() == b"last-good"


def test_save_commits_selected_price_atomically_and_stores_runtime_path(
        qtbot, tmp_path, monkeypatch):
    dialog, config_path, current = _dialog_with_runtime(qtbot, tmp_path)
    candidate = tmp_path / "supplier.xlsx"
    candidate.write_bytes(b"candidate")
    _mock_price(monkeypatch, count=25)
    monkeypatch.setattr(
        settings_dialog,
        "get_open_file_name",
        lambda *args, **kwargs: (str(candidate), "Excel (*.xlsx)"),
    )

    dialog._choose_price_file()
    dialog.save()

    assert current.read_bytes() == b"candidate"
    assert LocalConfig(config_path).get_source_path() == "runtime/carver/current.xlsx"
    assert dialog._pending_price_path is None


def test_settings_save_failure_restores_previous_price_and_yaml(
    qtbot, tmp_path, monkeypatch
):
    dialog, config_path, current = _dialog_with_runtime(qtbot, tmp_path)
    candidate = tmp_path / "supplier.xlsx"
    candidate.write_bytes(b"candidate")
    _mock_price(monkeypatch, count=25)
    monkeypatch.setattr(
        settings_dialog,
        "get_open_file_name",
        lambda *args, **kwargs: (str(candidate), "Excel (*.xlsx)"),
    )
    dialog._choose_price_file()
    original_yaml = config_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        dialog.local_cfg,
        "save",
        lambda: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        dialog.save()

    assert current.read_bytes() == b"last-good"
    assert config_path.read_text(encoding="utf-8") == original_yaml
    assert dialog.local_cfg.get_source_path() == ""
    assert not list(current.parent.glob(".current.backup.*.xlsx"))


def test_validation_requires_external_price_to_be_imported(
    qtbot, tmp_path, monkeypatch
):
    dialog, _config_path, _current = _dialog_with_runtime(qtbot, tmp_path)
    external = tmp_path / "external.xlsx"
    external.write_bytes(b"external")
    dialog.price_path_input.setText(str(external))
    dialog.category_input.setText("Категория")
    dialog.goods_type_input.setText("Вид")
    dialog.goods_subtype_input.setText("Подвид")
    dialog.markup_input.setValue(10)
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args: warnings.append(args)),
    )

    dialog._validate_and_accept()

    assert warnings
    assert "Выберите свежий файл" in warnings[0][2]
    assert dialog.result() == 0
