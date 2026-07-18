"""Pure calculation of bulk catalog changes before any YAML is mutated."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig

PriceMode = Literal["unchanged", "percent", "amount", "fixed", "reset"]
_PRICE_MODES = {"unchanged", "percent", "amount", "fixed", "reset"}


@dataclass(frozen=True)
class BulkRequest:
    target_keys: tuple[str, ...]
    publication: bool | None = None
    price_mode: PriceMode = "unchanged"
    price_value: Decimal | None = None


@dataclass(frozen=True)
class MemberPriceChange:
    series_key: str
    nc_code: str
    old_price: int | None
    new_price: int | None
    forced: bool


@dataclass(frozen=True)
class SeriesChange:
    key: str
    old_selected: bool
    new_selected: bool


@dataclass(frozen=True)
class BulkPreview:
    series_changes: tuple[SeriesChange, ...]
    price_changes: tuple[MemberPriceChange, ...]
    unknown_keys: tuple[str, ...] = ()
    skipped_without_price: tuple[str, ...] = ()
    skipped_below_cost: tuple[str, ...] = ()
    skipped_forced_reset: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.series_changes or self.price_changes)


def _validated_value(request: BulkRequest) -> Decimal | None:
    if request.price_mode not in _PRICE_MODES:
        raise ValueError("Неизвестный режим изменения цены")
    if request.price_mode in {"unchanged", "reset"}:
        return None
    if request.price_value is None:
        raise ValueError("Укажите значение изменения цены")
    value = Decimal(request.price_value)
    if request.price_mode == "percent" and not Decimal("-100") < value <= Decimal("10000"):
        raise ValueError("Процент должен быть больше -100 и не больше 10000")
    if request.price_mode == "fixed" and value <= 0:
        raise ValueError("Фиксированная цена должна быть больше нуля")
    return value


def _new_price(current: int, mode: PriceMode, value: Decimal) -> int:
    current_decimal = Decimal(current)
    if mode == "percent":
        calculated = current_decimal * (Decimal("1") + value / Decimal("100"))
    elif mode == "amount":
        calculated = current_decimal + value
    else:
        calculated = value
    result = int(calculated.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if result <= 0:
        raise ValueError("Итоговая цена должна быть больше нуля")
    return result


def build_bulk_preview(rows: list[CatalogRow], request: BulkRequest) -> BulkPreview:
    if not request.target_keys:
        raise ValueError("Выберите хотя бы один товар")
    value = _validated_value(request)
    rows_by_key = {row.key: row for row in rows}
    keys = tuple(dict.fromkeys(request.target_keys))
    unknown = tuple(key for key in keys if key not in rows_by_key)
    series_changes: list[SeriesChange] = []
    price_changes: list[MemberPriceChange] = []
    skipped_without_price: list[str] = []
    skipped_below_cost: list[str] = []
    skipped_forced_reset: list[str] = []

    for key in keys:
        row = rows_by_key.get(key)
        if row is None:
            continue
        if request.publication is not None and row.selected != request.publication:
            series_changes.append(SeriesChange(key, row.selected, request.publication))
        if request.price_mode == "unchanged":
            continue
        for member in row.members:
            if request.price_mode == "reset":
                if member.forced:
                    skipped_forced_reset.append(member.nc_code)
                else:
                    price_changes.append(MemberPriceChange(
                        key, member.nc_code, member.current_price, None, False))
                continue
            if not member.price_ok or member.current_price is None:
                skipped_without_price.append(member.nc_code)
                continue
            new_price = _new_price(member.current_price, request.price_mode, value)
            if member.cost is not None and new_price < member.cost:
                skipped_below_cost.append(member.nc_code)
                continue
            if new_price != member.current_price:
                price_changes.append(MemberPriceChange(
                    key, member.nc_code, member.current_price, new_price, member.forced))

    return BulkPreview(
        series_changes=tuple(series_changes),
        price_changes=tuple(price_changes),
        unknown_keys=unknown,
        skipped_without_price=tuple(skipped_without_price),
        skipped_below_cost=tuple(skipped_below_cost),
        skipped_forced_reset=tuple(skipped_forced_reset),
    )


def apply_bulk_preview(local_cfg: LocalConfig, preview: BulkPreview) -> None:
    """Persist a validated preview in one YAML save; never publishes externally."""
    if preview.unknown_keys:
        raise ValueError(f"Не найдены товары: {', '.join(preview.unknown_keys)}")
    if not preview.has_changes:
        raise ValueError("В операции нет изменений")
    for change in preview.price_changes:
        if change.forced and (
            change.new_price is None or not local_cfg.has_force_include(change.nc_code)
        ):
            raise ValueError(f"Не найдена принудительная позиция {change.nc_code}")
        if change.new_price is not None and change.new_price <= 0:
            raise ValueError(f"Некорректная цена для {change.nc_code}")

    for change in preview.series_changes:
        local_cfg.set_selected(change.key, change.new_selected)
    for change in preview.price_changes:
        if change.forced:
            local_cfg.set_force_price(change.nc_code, change.new_price)
        elif change.new_price is None:
            local_cfg.remove_manual_price(change.nc_code)
        else:
            local_cfg.set_manual_price(change.nc_code, change.new_price)
    local_cfg.save()
