"""Bounded, profile-scoped cache for the last successful remote catalog.

The cache is deliberately a display-only snapshot.  Publication selection is
never trusted from disk: it is recalculated from the active :class:`LocalConfig`
every time the snapshot is loaded.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from avito_studio.atomic_io import atomic_write_text
from avito_studio.catalog_service import CatalogMember, CatalogRow
from avito_studio.local_config import LocalConfig

CACHE_SCHEMA_VERSION = 1
MAX_CACHE_BYTES = 8 * 1024 * 1024
MAX_CACHE_ROWS = 20_000
MAX_MEMBERS_PER_ROW = 500
MAX_TOTAL_MEMBERS = 100_000
MAX_STRING_CHARS = 32_768

# A mapping, instead of interpolating the profile into a path, makes traversal
# impossible even if this module is called outside the normal profile selector.
_CACHE_FILENAMES = {
    "conditioners": "conditioners.json",
    "wreaths": "wreaths.json",
}
_ROW_FIELDS = {
    "key",
    "source",
    "brand",
    "series",
    "sizes",
    "stock_total",
    "has_card",
    "forced",
    "selected",
    "representative_nc",
    "price_range",
    "avito_status",
    "members",
    "ad_supplier_sku",
    "ad_id_revision",
}
_MEMBER_FIELDS = {
    "nc_code",
    "current_price",
    "cost",
    "price_ok",
    "forced",
    "supplier_sku",
    "product_kind",
    "ad_id_revision",
}


class CatalogCacheError(ValueError):
    """The cache is absent, unsafe, oversized, or incompatible."""


def default_cache_dir() -> Path:
    """Return ``%LOCALAPPDATA%/AvitoStudio/cache`` without creating it."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise CatalogCacheError(
            "Переменная LOCALAPPDATA не задана; локальный кэш недоступен"
        )
    return Path(local_app_data) / "AvitoStudio" / "cache"


def cache_path(profile_key: str, cache_dir: str | Path | None = None) -> Path:
    """Resolve a cache path only for an explicitly supported server profile."""
    if not isinstance(profile_key, str) or profile_key not in _CACHE_FILENAMES:
        raise CatalogCacheError(
            f"Кэш запрещён для неизвестного профиля: {profile_key!r}"
        )
    root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    return root / _CACHE_FILENAMES[profile_key]


def save_catalog_cache(
    profile_key: str,
    rows: list[CatalogRow],
    cache_dir: str | Path | None = None,
) -> Path:
    """Atomically save a validated catalog snapshot and return its path."""
    if not isinstance(rows, list):
        raise CatalogCacheError("Каталог для кэша должен быть списком")
    payload = {
        "version": CACHE_SCHEMA_VERSION,
        "profile": profile_key,
        "saved_at": datetime.now(UTC).isoformat(),
        "rows": [_row_to_dict(row) for row in rows],
    }
    # Validate our own output too.  This catches a future model change before an
    # incompatible/oversized snapshot replaces the last known-good file.
    _validate_payload(payload, profile_key)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_CACHE_BYTES:
        raise CatalogCacheError(
            f"Каталог слишком большой для кэша: {len(encoded)} байт "
            f"(лимит {MAX_CACHE_BYTES})"
        )
    path = cache_path(profile_key, cache_dir)
    atomic_write_text(path, encoded.decode("utf-8") + "\n")
    return path


def load_catalog_cache(
    profile_key: str,
    local_cfg: LocalConfig,
    cache_dir: str | Path | None = None,
) -> list[CatalogRow]:
    """Load a bounded snapshot and recalculate its selection from ``local_cfg``."""
    path = cache_path(profile_key, cache_dir)
    try:
        with path.open("rb") as stream:
            encoded = stream.read(MAX_CACHE_BYTES + 1)
    except FileNotFoundError as exc:
        raise CatalogCacheError(
            f"Сохранённый каталог профиля «{profile_key}» ещё не создан"
        ) from exc
    except OSError as exc:
        raise CatalogCacheError(f"Не удалось прочитать кэш каталога: {exc}") from exc
    if len(encoded) > MAX_CACHE_BYTES:
        raise CatalogCacheError(
            f"Кэш каталога превышает безопасный лимит {MAX_CACHE_BYTES} байт"
        )
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogCacheError("Кэш каталога повреждён: некорректный JSON") from exc
    _validate_payload(payload, profile_key)
    return [
        _row_from_dict(row, local_cfg.is_selected(_string(row["key"], "rows[].key")))
        for row in payload["rows"]
    ]


def _row_to_dict(row: CatalogRow) -> dict[str, Any]:
    if not isinstance(row, CatalogRow):
        raise CatalogCacheError("В кэш можно сохранить только CatalogRow")
    return {
        "key": row.key,
        "source": row.source,
        "brand": row.brand,
        "series": row.series,
        "sizes": row.sizes,
        "stock_total": row.stock_total,
        "has_card": row.has_card,
        "forced": row.forced,
        "selected": row.selected,
        "representative_nc": row.representative_nc,
        "price_range": row.price_range,
        "avito_status": row.avito_status,
        "members": [_member_to_dict(member) for member in row.members],
        "ad_supplier_sku": row.ad_supplier_sku,
        "ad_id_revision": row.ad_id_revision,
    }


def _member_to_dict(member: CatalogMember) -> dict[str, Any]:
    if not isinstance(member, CatalogMember):
        raise CatalogCacheError("В кэш можно сохранить только CatalogMember")
    return {
        "nc_code": member.nc_code,
        "current_price": member.current_price,
        "cost": member.cost,
        "price_ok": member.price_ok,
        "forced": member.forced,
        "supplier_sku": member.supplier_sku,
        "product_kind": member.product_kind,
        "ad_id_revision": member.ad_id_revision,
    }


def _row_from_dict(value: dict[str, Any], selected: bool) -> CatalogRow:
    return CatalogRow(
        key=_string(value["key"], "rows[].key"),
        source=_string(value["source"], "rows[].source"),
        brand=_string(value["brand"], "rows[].brand"),
        series=_string(value["series"], "rows[].series"),
        sizes=_string(value["sizes"], "rows[].sizes"),
        stock_total=_integer(value["stock_total"], "rows[].stock_total", minimum=0),
        has_card=_boolean(value["has_card"], "rows[].has_card"),
        forced=_boolean(value["forced"], "rows[].forced"),
        selected=selected,
        representative_nc=_string(
            value["representative_nc"], "rows[].representative_nc"
        ),
        price_range=_string(value["price_range"], "rows[].price_range"),
        avito_status=_optional_string(value["avito_status"], "rows[].avito_status"),
        members=tuple(_member_from_dict(member) for member in value["members"]),
        ad_supplier_sku=_string(
            value["ad_supplier_sku"], "rows[].ad_supplier_sku"
        ),
        ad_id_revision=_integer(
            value["ad_id_revision"], "rows[].ad_id_revision", minimum=0
        ),
    )


def _member_from_dict(value: dict[str, Any]) -> CatalogMember:
    return CatalogMember(
        nc_code=_string(value["nc_code"], "members[].nc_code"),
        current_price=_optional_integer(
            value["current_price"], "members[].current_price", minimum=0
        ),
        cost=_optional_integer(value["cost"], "members[].cost", minimum=0),
        price_ok=_boolean(value["price_ok"], "members[].price_ok"),
        forced=_boolean(value["forced"], "members[].forced"),
        supplier_sku=_string(value["supplier_sku"], "members[].supplier_sku"),
        product_kind=_string(value["product_kind"], "members[].product_kind"),
        ad_id_revision=_integer(
            value["ad_id_revision"], "members[].ad_id_revision", minimum=0
        ),
    )


def _validate_payload(payload: Any, profile_key: str) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "profile",
        "saved_at",
        "rows",
    }:
        raise CatalogCacheError("Кэш каталога имеет неизвестную структуру")
    version = _integer(payload["version"], "version", minimum=1)
    if version != CACHE_SCHEMA_VERSION:
        raise CatalogCacheError("Версия кэша каталога не поддерживается")
    if payload["profile"] != profile_key:
        raise CatalogCacheError("Кэш принадлежит другому профилю")
    saved_at = _string(payload["saved_at"], "saved_at", maximum=128)
    try:
        timestamp = datetime.fromisoformat(saved_at)
    except ValueError as exc:
        raise CatalogCacheError("Поле saved_at содержит неверную дату") from exc
    if timestamp.tzinfo is None:
        raise CatalogCacheError("Поле saved_at должно содержать часовой пояс")
    rows = payload["rows"]
    if not isinstance(rows, list):
        raise CatalogCacheError("Поле rows в кэше должно быть списком")
    if len(rows) > MAX_CACHE_ROWS:
        raise CatalogCacheError(
            f"В кэше слишком много строк: {len(rows)} (лимит {MAX_CACHE_ROWS})"
        )
    seen_keys: set[str] = set()
    member_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _ROW_FIELDS:
            raise CatalogCacheError(f"Строка кэша #{index + 1} имеет неверную схему")
        key = _string(row["key"], f"rows[{index}].key")
        if not key:
            raise CatalogCacheError(f"Строка кэша #{index + 1} не имеет ключа")
        if key in seen_keys:
            raise CatalogCacheError(f"В кэше повторяется ключ серии: {key!r}")
        seen_keys.add(key)
        members = row["members"]
        if not isinstance(members, list):
            raise CatalogCacheError(
                f"Поле members строки #{index + 1} должно быть списком"
            )
        if len(members) > MAX_MEMBERS_PER_ROW:
            raise CatalogCacheError(
                f"Слишком много позиций в строке #{index + 1}: {len(members)}"
            )
        member_count += len(members)
        if member_count > MAX_TOTAL_MEMBERS:
            raise CatalogCacheError(
                f"В кэше больше {MAX_TOTAL_MEMBERS} вложенных позиций"
            )
        for member_index, member in enumerate(members):
            if not isinstance(member, dict) or set(member) != _MEMBER_FIELDS:
                raise CatalogCacheError(
                    f"Позиция #{member_index + 1} строки #{index + 1} "
                    "имеет неверную схему"
                )
            _member_from_dict(member)
        _row_from_dict(row, selected=False)


def _string(value: Any, field: str, maximum: int = MAX_STRING_CHARS) -> str:
    if not isinstance(value, str):
        raise CatalogCacheError(f"Поле {field} должно быть строкой")
    if len(value) > maximum:
        raise CatalogCacheError(f"Поле {field} превышает лимит длины")
    if "\0" in value:
        raise CatalogCacheError(f"Поле {field} содержит запрещённый NUL-символ")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogCacheError(f"Поле {field} должно быть true/false")
    return value


def _integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogCacheError(f"Поле {field} должно быть целым числом")
    if minimum is not None and value < minimum:
        raise CatalogCacheError(f"Поле {field} меньше допустимого значения")
    return value


def _optional_integer(
    value: Any,
    field: str,
    *,
    minimum: int | None = None,
) -> int | None:
    return None if value is None else _integer(value, field, minimum=minimum)


def _object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CatalogCacheError(f"В JSON-кэше повторяется поле {key!r}")
        value[key] = item
    return value
