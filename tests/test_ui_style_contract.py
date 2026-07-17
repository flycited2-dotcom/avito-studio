"""Regression contracts for the shared Avito Studio dialog visual language.

These tests intentionally assert semantic names and roles, not pixel colours.  The
theme owns rendering; dialogs only compose the shared shell and declare intent.
"""
from __future__ import annotations

import inspect

import pytest
from PySide6.QtWidgets import QCheckBox, QFrame, QPushButton, QTabWidget, QWidget

from avito_studio import add_forced_dialog, edit_dialog, theme, ui_components
from avito_studio.add_forced_dialog import AddForcedProductDialog
from avito_studio.catalog_service import CatalogRow
from avito_studio.edit_dialog import EditSeriesDialog
from avito_studio.local_config import LocalConfig


FIXTURE_CFG = """\
catalog:
  force_include: {}
  manual_photos: {}
  manual_products: {}
  selected_series: []
"""


class FakeSsh:
    def run(self, _command):
        return ""

    def put(self, _remote_path, _data):
        return None


def _local_cfg(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_CFG, encoding="utf-8")
    return LocalConfig(path)


def _edit_dialog(tmp_path):
    bridge_root = tmp_path / "bridge"
    (bridge_root / "avito-descriptions").mkdir(parents=True)
    (bridge_root / "avito-descriptions" / "manifest.json").write_text(
        "{}", encoding="utf-8")
    row = CatalogRow(
        key="breeze|funai|sensei 2.0",
        source="breeze",
        brand="Funai",
        series="Sensei 2.0",
        sizes="7/9 тыс. BTU",
        stock_total=5,
        has_card=True,
        forced=False,
        selected=True,
        representative_nc="НС-2",
        price_range="25990 ₽",
    )
    return EditSeriesDialog(row, bridge_root, _local_cfg(tmp_path), FakeSsh())


def _assert_shared_dialog_contract(dialog):
    page = dialog.findChild(QWidget, "dialogPage")
    header = dialog.findChild(QFrame, "dialogHeader")
    footer = dialog.findChild(QFrame, "dialogFooter")
    sections = dialog.findChildren(QFrame, "formSection")

    assert page is not None, "dialog content must use QWidget#dialogPage"
    assert header is not None, "dialog must use the shared dialog_header()"
    assert footer is not None, "dialog actions must live in the shared dialog_footer()"
    assert sections, "dialog fields must be grouped into shared FormSection cards"

    primary = [
        button for button in dialog.findChildren(QPushButton)
        if button.property("role") == "primary"
    ]
    assert primary == [dialog.save_btn], "there must be exactly one primary CTA"
    assert dialog.save_btn.isDefault(), "the primary CTA must also be the Enter action"

    footer_buttons = footer.findChildren(QPushButton)
    assert dialog.save_btn in footer_buttons
    assert any(button.property("role") == "secondary" for button in footer_buttons)


def test_shared_component_builders_expose_semantic_contract(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    header = ui_components.dialog_header("Заголовок", "Подзаголовок", parent=host)
    section = ui_components.FormSection("Карточка", "Подсказка", parent=host)
    primary = ui_components.role_button("Сохранить", "primary", host)
    cancel = ui_components.role_button("Отмена", "secondary", host)
    footer = ui_components.dialog_footer([cancel, primary], parent=host)

    assert header.objectName() == "dialogHeader"
    assert section.objectName() == "formSection"
    assert footer.objectName() == "dialogFooter"
    assert primary.property("role") == "primary"
    assert cancel.property("role") == "secondary"
    with pytest.raises(ValueError, match="Unknown button role"):
        ui_components.set_button_role(primary, "neon")


def test_add_product_dialog_uses_shared_shell_roles_tabs_and_checks(qtbot, tmp_path):
    dialog = AddForcedProductDialog(_local_cfg(tmp_path), FakeSsh())
    qtbot.addWidget(dialog)

    _assert_shared_dialog_contract(dialog)
    tabs = dialog.findChild(QTabWidget)
    assert tabs is not None and tabs.count() == 2
    assert dialog.manual_inverter_box in dialog.findChildren(QCheckBox)


def test_edit_series_dialog_uses_shared_shell_and_single_primary_cta(qtbot, tmp_path):
    dialog = _edit_dialog(tmp_path)
    qtbot.addWidget(dialog)

    _assert_shared_dialog_contract(dialog)
    assert len(dialog.findChildren(QFrame, "formSection")) >= 2


@pytest.mark.parametrize(
    "module,method_name",
    [
        (add_forced_dialog, "_choose_photo"),
        (edit_dialog, "_choose_photo"),
    ],
)
def test_dialog_photo_picker_is_routed_through_themed_helper(module, method_name):
    source = inspect.getsource(getattr(
        module.AddForcedProductDialog
        if module is add_forced_dialog else module.EditSeriesDialog,
        method_name,
    ))
    assert "get_open_file_name" in source
    assert "QFileDialog.getOpenFileName(" not in source


def test_file_dialog_helper_forces_non_native_surface():
    source = inspect.getsource(ui_components.get_open_file_name)
    assert "DontUseNativeDialog" in source
    assert "QFileDialog.getOpenFileName(" not in source


def test_theme_defines_every_shared_dialog_surface():
    required_selectors = (
        "QWidget#dialogPage",
        "QFrame#dialogHeader",
        "QFrame#formSection",
        "QFrame#dialogFooter",
        'QPushButton[role="primary"]',
        'QPushButton[role="secondary"]',
        "QTabBar::tab:selected",
        "QCheckBox::indicator:checked",
        "QFileDialog QTreeView",
    )
    for selector in required_selectors:
        assert selector in theme._QSS, f"missing shared theme selector: {selector}"
