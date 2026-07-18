"""Profile-specific definitions and serialization for Studio manual products."""
from __future__ import annotations

from dataclasses import dataclass

from avito_studio.local_config import LocalConfig


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "text"
    required: bool = False
    choices: tuple[tuple[str, object], ...] = ()
    suffix: str = ""
    default: object = ""


@dataclass(frozen=True)
class ManualFormSpec:
    profile_key: str
    label: str
    allow_nc_code: bool
    fields: tuple[FieldSpec, ...]
    brand_default: str = ""
    series_required: bool = False


_FORMS = {
    "conditioners": ManualFormSpec(
        profile_key="conditioners",
        label="Кондиционеры",
        allow_nc_code=True,
        series_required=True,
        fields=(
            FieldSpec("product_type", "Тип кондиционера", "combo", True, (
                ("Настенная сплит-система", 2),
                ("Полупромышленный кондиционер", 6),
                ("Мобильный кондиционер", 7),
            )),
            FieldSpec("btu", "Типоразмер", "int", True, suffix=" тыс. BTU"),
            FieldSpec("inverter", "Исполнение", "bool", default=False),
        ),
    ),
    "carver": ManualFormSpec(
        profile_key="carver",
        label="Генераторы CARVER",
        allow_nc_code=False,
        brand_default="CARVER",
        fields=(
            FieldSpec("product_type", "Тип товара", "combo", True, (
                ("Генератор", "generator"),
                ("Автоматика ATS", "ats"),
            )),
            FieldSpec("fuel_type", "Топливо", "combo", choices=(
                ("Не указано", ""), ("Бензин", "Бензин"), ("Дизель", "Дизель"),
            )),
            FieldSpec("voltage", "Напряжение", "combo", choices=(
                ("Не указано", ""), ("220 В", "220 В"), ("220/380 В", "220/380 В"),
            )),
            FieldSpec("rated_power", "Номинальная мощность", "float", suffix=" кВт"),
            FieldSpec("maximum_power", "Максимальная мощность", "float", suffix=" кВт"),
            FieldSpec("start_type", "Тип запуска", "combo", choices=(
                ("Не указано", ""), ("Ручной", "Ручной"),
                ("Электрический", "Электрический"), ("Автоматический", "Автоматический"),
            )),
        ),
    ),
    "appliances": ManualFormSpec(
        profile_key="appliances",
        label="Бытовая техника",
        allow_nc_code=False,
        fields=(FieldSpec("group", "Группа товара", "combo", True),),
    ),
    "wreaths": ManualFormSpec(
        profile_key="wreaths",
        label="Венки и корзины",
        allow_nc_code=False,
        fields=(
            FieldSpec("product_type", "Тип товара", "combo", True, (
                ("Венок", "wreath"), ("Корзина", "basket"),
            )),
            FieldSpec("shape", "Форма"),
            FieldSpec("width", "Ширина / диаметр"),
            FieldSpec("height", "Высота"),
            FieldSpec("color", "Цветовая гамма"),
            FieldSpec("materials", "Материалы / состав"),
        ),
    ),
}

_APPLIANCE_DEFAULT = ("Мощность", "Ширина", "Высота", "Глубина", "Цвет")
_APPLIANCE_MIXER = ("Мощность", "Количество скоростей", "Объём чаши / кувшина", "Насадки")
_APPLIANCE_COLD = (
    "Ширина", "Высота", "Глубина", "Общий объём", "Скорость заморозки", "Цвет")
_APPLIANCE_LAUNDRY = (
    "Загрузка", "Скорость отжима", "Ширина", "Высота", "Глубина", "Цвет")


def form_spec(profile_key: str) -> ManualFormSpec:
    try:
        return _FORMS[profile_key]
    except KeyError:
        raise KeyError(f"Неизвестный профиль ручного товара: {profile_key}") from None


def appliance_groups(local_cfg: LocalConfig) -> tuple[str, ...]:
    profile = local_cfg.data.get("profile", {}) or {}
    options = profile.get("source_options", {}) or {}
    return tuple(str(value).strip() for value in options.get("selected_groups", [])
                 if str(value).strip())


def suggested_characteristics(profile_key: str, group: str = "") -> tuple[str, ...]:
    if profile_key == "conditioners":
        return ("Площадь помещения", "Мощность охлаждения", "Мощность обогрева", "Хладагент")
    if profile_key == "carver":
        return ("Объём топливного бака", "Время работы", "Уровень шума", "Вес")
    if profile_key == "wreaths":
        return ()
    if profile_key != "appliances":
        form_spec(profile_key)
    normalized = (group or "").casefold()
    if "миксер" in normalized or "блендер" in normalized:
        return _APPLIANCE_MIXER
    if any(token in normalized for token in ("холодил", "морозил", "лар")):
        return _APPLIANCE_COLD
    if "стирал" in normalized or "сушиль" in normalized:
        return _APPLIANCE_LAUNDRY
    return _APPLIANCE_DEFAULT


def _positive_number(value, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Поле «{field}» должно быть числом") from None
    if number <= 0:
        raise ValueError(f"Поле «{field}» должно быть больше нуля")
    return number


def _number_text(value) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else format(number, "g")


def _characteristics(rows: list[tuple[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw_name, raw_value in rows:
        name = str(raw_name or "").strip()
        value = str(raw_value or "").strip()
        if not name and not value:
            continue
        if name and not value:
            continue
        if not name:
            raise ValueError("У каждой характеристики должны быть название и значение")
        normalized = name.casefold()
        if normalized in seen:
            raise ValueError(f"Характеристика «{name}» повторяется")
        seen.add(normalized)
        result[name] = value
    return result


def serialize_manual_product(
    profile_key: str,
    common: dict,
    profile_values: dict,
    characteristic_rows: list[tuple[str, str]],
) -> dict:
    """Validate form values and return the YAML mapping consumed by Bridge."""
    form_spec(profile_key)
    brand = str(common.get("brand") or "").strip()
    title = str(common.get("title") or "").strip()
    series = str(common.get("series") or "").strip()
    if not title:
        raise ValueError("Название / модель обязательно")
    if not brand and profile_key != "wreaths":
        raise ValueError("Бренд обязателен")
    if profile_key == "conditioners" and not series:
        raise ValueError("Серия обязательна для кондиционера")
    price = _positive_number(common.get("price"), "Финальная цена")
    stock = _positive_number(common.get("stock", 1), "Количество")
    if not stock.is_integer():
        raise ValueError("Количество должно быть целым числом")
    photos = [str(value).strip() for value in (common.get("photos") or [])
              if str(value).strip()]
    if not photos:
        raise ValueError("Требуется фотография товара")

    tech = _characteristics(characteristic_rows)
    result = {
        "brand": brand,
        "title": title,
        "series": series,
        "price": int(price) if price.is_integer() else price,
        "stock": int(stock),
        "photos": photos,
        "tech": tech,
    }
    description = str(common.get("description") or "").strip()
    if description:
        result["description"] = description

    if profile_key == "conditioners":
        category_id = int(profile_values.get("product_type") or 0)
        if category_id not in {2, 6, 7}:
            raise ValueError("Выберите тип кондиционера")
        btu = _positive_number(profile_values.get("btu"), "Типоразмер")
        result["category_id"] = category_id
        result["btu"] = int(btu) if btu.is_integer() else btu
        if profile_values.get("inverter"):
            if "инвертор" not in series.casefold() and "inverter" not in series.casefold():
                result["series"] = series + " Inverter"
            tech["Тип компрессора"] = "Инвертор"
        if description:
            tech["Особенности"] = description
        return result

    if profile_key == "carver":
        group = str(profile_values.get("product_type") or "").strip()
        if group not in {"generator", "ats"}:
            raise ValueError("Выберите тип товара CARVER")
        result["group"] = group
        result["series"] = "Генераторы CARVER" if group == "generator" else "Автоматика ATS"
        mappings = (
            ("fuel_type", "Топливо"),
            ("voltage", "Напряжение"),
            ("rated_power", "Номинальная мощность, кВт"),
            ("maximum_power", "Максимальная мощность, кВт"),
            ("start_type", "Тип запуска"),
        )
        for key, label in mappings:
            value = profile_values.get(key)
            if value not in (None, "", 0, 0.0):
                tech[label] = (_number_text(value)
                               if key in {"rated_power", "maximum_power"} else str(value).strip())
        tags = {"Brand": brand, "Model": title}
        for key, tag in (
            ("fuel_type", "FuelType"), ("voltage", "Voltage"),
            ("rated_power", "RatedPower"), ("maximum_power", "MaximumPower"),
        ):
            value = profile_values.get(key)
            if value not in (None, "", 0, 0.0):
                tags[tag] = (_number_text(value)
                             if key in {"rated_power", "maximum_power"} else str(value).strip())
        result["avito_tags"] = tags
        return result

    if profile_key == "appliances":
        group = str(profile_values.get("group") or "").strip()
        if not group:
            raise ValueError("Выберите группу бытовой техники")
        result["group"] = group
        result["series"] = series or group
        return result

    product_type = str(profile_values.get("product_type") or "").strip()
    if product_type not in {"wreath", "basket"}:
        raise ValueError("Выберите венок или корзину")
    result["group"] = product_type
    result["series"] = series or title
    for key, label in (
        ("shape", "Форма"), ("width", "Ширина / диаметр"),
        ("height", "Высота"), ("color", "Цветовая гамма"),
        ("materials", "Материалы / состав"),
    ):
        value = str(profile_values.get(key) or "").strip()
        if value:
            tech[label] = value
    return result
