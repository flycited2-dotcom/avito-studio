import pytest

from avito_studio.local_config import LocalConfig
from avito_studio.manual_product_forms import (
    appliance_groups,
    form_spec,
    serialize_manual_product,
    suggested_characteristics,
)


def test_profile_schemas_do_not_leak_conditioner_fields():
    assert form_spec("conditioners").allow_nc_code is True
    assert form_spec("carver").allow_nc_code is False
    assert form_spec("wreaths").allow_nc_code is False
    assert form_spec("appliances").allow_nc_code is False
    assert {field.key for field in form_spec("carver").fields} >= {
        "product_type", "fuel_type", "voltage", "rated_power",
        "maximum_power", "start_type",
    }
    for key in ("carver", "wreaths", "appliances"):
        assert "btu" not in {field.key for field in form_spec(key).fields}
        assert "inverter" not in {field.key for field in form_spec(key).fields}


def test_unknown_profile_fails_closed():
    with pytest.raises(KeyError, match="unknown"):
        form_spec("unknown")


def test_appliance_groups_come_from_active_yaml(tmp_path):
    path = tmp_path / "appliances.yaml"
    path.write_text(
        "profile:\n"
        "  source_options:\n"
        "    selected_groups: [Миксеры, Холодильники]\n"
        "catalog: {manual_products: {}}\n",
        encoding="utf-8",
    )
    assert appliance_groups(LocalConfig(path)) == ("Миксеры", "Холодильники")


def test_appliance_suggestions_follow_group_without_btu():
    mixer = suggested_characteristics("appliances", "Миксеры")
    fridge = suggested_characteristics(
        "appliances", "Холодильники с нижней морозильной камерой")
    default = suggested_characteristics("appliances", "Неизвестная группа")
    assert "Мощность" in mixer and "Количество скоростей" in mixer
    assert "Скорость заморозки" in fridge and "Общий объём" in fridge
    assert default == ("Мощность", "Ширина", "Высота", "Глубина", "Цвет")
    assert all("BTU" not in value for value in mixer + fridge + default)


def _common(**overrides):
    values = {
        "brand": "CARVER",
        "title": "PPG-1900i",
        "series": "",
        "price": 43200,
        "stock": 1,
        "photos": ["https://i/product.jpg"],
        "description": "Новый товар.",
    }
    values.update(overrides)
    return values


def test_serialize_carver_maps_fields_to_tech_and_avito_tags():
    result = serialize_manual_product(
        "carver",
        _common(),
        {
            "product_type": "generator",
            "fuel_type": "Бензин",
            "voltage": "220 В",
            "rated_power": 1.7,
            "maximum_power": 1.9,
            "start_type": "Ручной",
        },
        [("Вес", "22 кг")],
    )
    assert result["group"] == "generator"
    assert result["series"] == "Генераторы CARVER"
    assert result["tech"]["Номинальная мощность, кВт"] == "1.7"
    assert result["tech"]["Вес"] == "22 кг"
    assert result["avito_tags"] == {
        "Brand": "CARVER",
        "Model": "PPG-1900i",
        "FuelType": "Бензин",
        "Voltage": "220 В",
        "RatedPower": "1.7",
        "MaximumPower": "1.9",
    }


def test_serialize_appliance_keeps_group_and_arbitrary_characteristics():
    result = serialize_manual_product(
        "appliances",
        _common(brand="Kitfort", title="Миксер KT-100", price=5990),
        {"group": "Миксеры"},
        [("Мощность", "600 Вт"), ("Количество скоростей", "5")],
    )
    assert result["group"] == "Миксеры"
    assert result["series"] == "Миксеры"
    assert result["tech"]["Количество скоростей"] == "5"
    assert "btu" not in result and "category_id" not in result


def test_serialize_wreath_allows_empty_brand_and_maps_profile_fields():
    result = serialize_manual_product(
        "wreaths",
        _common(brand="", title="Венок Аврора", price=3500),
        {
            "product_type": "wreath",
            "shape": "Овальная",
            "width": "70 см",
            "height": "120 см",
            "color": "Красный и зелёный",
            "materials": "Искусственная хвоя, цветы",
        },
        [],
    )
    assert result["group"] == "wreath"
    assert result["tech"]["Форма"] == "Овальная"
    assert result["tech"]["Материалы / состав"] == "Искусственная хвоя, цветы"


def test_serialize_conditioner_keeps_legacy_contract():
    result = serialize_manual_product(
        "conditioners",
        _common(brand="Ballu", title="BSAG-09", series="Eco", price=30000),
        {"product_type": 2, "btu": 9, "inverter": True},
        [("Площадь помещения", "до 25 м²")],
    )
    assert result["category_id"] == 2
    assert result["btu"] == 9
    assert result["tech"]["Тип компрессора"] == "Инвертор"
    assert result["tech"]["Площадь помещения"] == "до 25 м²"
    assert result["description"] == "Новый товар."
    assert "Особенности" not in result["tech"]


def test_duplicate_characteristic_names_are_rejected():
    with pytest.raises(ValueError, match="повторяется"):
        serialize_manual_product(
            "appliances",
            _common(brand="Kitfort", title="Миксер", price=5990),
            {"group": "Миксеры"},
            [("Мощность", "600 Вт"), (" Мощность ", "700 Вт")],
        )


@pytest.mark.parametrize("price", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_price_is_rejected(price):
    with pytest.raises(ValueError, match="Финальная цена"):
        serialize_manual_product(
            "carver",
            _common(price=price),
            {"product_type": "generator"},
            [],
        )
