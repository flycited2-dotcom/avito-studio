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
    path = tmp_path / "carver.yaml"
    _config(path)
    local_cfg = LocalConfig(path)
    dlg = CarverPublishSettingsDialog(local_cfg)
    qtbot.addWidget(dlg)
    dlg.category_input.setText("Для дома и дачи")
    dlg.goods_type_input.setText("Садовая техника")
    dlg.markup_input.setValue(12.5)
    dlg.rounding_combo.setCurrentIndex(dlg.rounding_combo.findData("up_to_90"))
    dlg.save()

    saved = LocalConfig(path).get_publication_settings()
    assert saved == {
        "category": "Для дома и дачи",
        "goods_type": "Садовая техника",
        "markup_pct": 12.5,
        "rounding": "up_to_90",
        "price_confirmed": False,
    }


def test_carver_zero_markup_can_be_explicitly_confirmed(qtbot, tmp_path):
    path = tmp_path / "carver.yaml"
    _config(path)
    local_cfg = LocalConfig(path)
    dlg = CarverPublishSettingsDialog(local_cfg)
    qtbot.addWidget(dlg)
    dlg.category_input.setText("Для дома и дачи")
    dlg.goods_type_input.setText("Садовая техника")
    dlg.markup_input.setValue(0)
    dlg.price_confirmed.setChecked(True)
    dlg.save()

    row = CatalogRow(
        key="carver_xlsx|item|carver:PPG-1900IS", source="carver_xlsx", brand="CARVER",
        series="Генератор CARVER PPG-1900IS", sizes="—", stock_total=1,
        has_card=True, forced=False, selected=True,
    )
    assert carver_publish_issues(path, [row]) == []
