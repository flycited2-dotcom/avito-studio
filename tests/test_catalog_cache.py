import json
from copy import deepcopy
from dataclasses import replace

import pytest

from avito_studio.catalog_cache import (
    CatalogCacheError,
    cache_path,
    load_catalog_cache,
    save_catalog_cache,
)
from avito_studio.catalog_service import CatalogMember, CatalogRow
from avito_studio.local_config import LocalConfig


def _config(tmp_path, selected='["cache-row"]'):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"catalog:\n  selected_series: {selected}\n",
        encoding="utf-8",
    )
    return LocalConfig(path)


def _row(selected=False):
    return CatalogRow(
        key="cache-row",
        source="breeze",
        brand="Funai",
        series="Sensei",
        sizes="7 тыс. BTU",
        stock_total=3,
        has_card=True,
        forced=False,
        selected=selected,
        representative_nc="НС-7",
        price_range="25990 ₽",
        avito_status="Активно",
        members=(
            CatalogMember(
                nc_code="НС-7",
                current_price=25_990,
                cost=20_000,
                price_ok=True,
                forced=False,
                supplier_sku="SKU-7",
                product_kind="split",
                ad_id_revision=2,
            ),
        ),
        ad_supplier_sku="SKU-7",
        ad_id_revision=3,
    )


def test_catalog_cache_roundtrips_models_and_recalculates_selection(tmp_path):
    cache_dir = tmp_path / "cache"
    original = _row(selected=False)
    config = _config(tmp_path)

    path = save_catalog_cache("conditioners", [original], cache_dir)
    loaded = load_catalog_cache("conditioners", config, cache_dir)

    assert path == cache_dir / "conditioners.json"
    assert loaded == [replace(original, selected=True)]
    assert loaded[0].members == original.members
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert not list(cache_dir.glob("*.tmp"))


@pytest.mark.parametrize(
    "contents",
    [
        "{broken json",
        (
            '{"version":1,"profile":"conditioners",'
            '"saved_at":"2026-07-25T12:00:00+00:00","rows":{}}'
        ),
    ],
)
def test_catalog_cache_rejects_corrupt_json_or_schema(tmp_path, contents):
    path = cache_path("conditioners", tmp_path / "cache")
    path.parent.mkdir()
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(CatalogCacheError, match="повреждён|rows"):
        load_catalog_cache("conditioners", _config(tmp_path), path.parent)


def test_catalog_cache_rejects_oversize_file_before_json_parse(
    tmp_path, monkeypatch
):
    import avito_studio.catalog_cache as cache

    monkeypatch.setattr(cache, "MAX_CACHE_BYTES", 64)
    path = cache_path("conditioners", tmp_path / "cache")
    path.parent.mkdir()
    path.write_bytes(b"{" + b"x" * 64)

    with pytest.raises(CatalogCacheError, match="безопасный лимит"):
        load_catalog_cache("conditioners", _config(tmp_path), path.parent)


def test_catalog_cache_default_path_is_scoped_to_local_app_data(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    assert cache_path("wreaths") == (
        tmp_path / "Local" / "AvitoStudio" / "cache" / "wreaths.json"
    )


@pytest.mark.parametrize(
    "profile_key",
    ["../conditioners", "..\\wreaths", "/absolute", "carver", "", None],
)
def test_catalog_cache_profile_allowlist_prevents_path_traversal(
    tmp_path, profile_key
):
    with pytest.raises(CatalogCacheError, match="неизвестного профиля"):
        cache_path(profile_key, tmp_path / "cache")
    assert not (tmp_path / "conditioners.json").exists()


def _valid_payload(tmp_path):
    path = save_catalog_cache("conditioners", [_row()], tmp_path / "cache")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_payload(tmp_path, payload):
    path = cache_path("conditioners", tmp_path / "cache")
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_catalog_cache_requires_local_app_data_for_default_location(
    monkeypatch
):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(CatalogCacheError, match="LOCALAPPDATA"):
        cache_path("conditioners")


def test_catalog_cache_rejects_non_model_output_before_replacing_cache(
    tmp_path
):
    with pytest.raises(CatalogCacheError, match="списком"):
        save_catalog_cache("conditioners", tuple(), tmp_path / "cache")
    with pytest.raises(CatalogCacheError, match="CatalogRow"):
        save_catalog_cache("conditioners", [object()], tmp_path / "cache")
    broken_member = replace(_row(), members=(object(),))
    with pytest.raises(CatalogCacheError, match="CatalogMember"):
        save_catalog_cache("conditioners", [broken_member], tmp_path / "cache")


def test_catalog_cache_rejects_oversize_generated_snapshot(
    tmp_path, monkeypatch
):
    import avito_studio.catalog_cache as cache

    monkeypatch.setattr(cache, "MAX_CACHE_BYTES", 64)
    with pytest.raises(CatalogCacheError, match="слишком большой"):
        save_catalog_cache("conditioners", [_row()], tmp_path / "cache")
    assert not cache_path("conditioners", tmp_path / "cache").exists()


def test_catalog_cache_reports_missing_and_unreadable_snapshot(tmp_path):
    cache_dir = tmp_path / "cache"
    with pytest.raises(CatalogCacheError, match="ещё не создан"):
        load_catalog_cache("conditioners", _config(tmp_path), cache_dir)

    path = cache_path("conditioners", cache_dir)
    path.mkdir(parents=True)
    with pytest.raises(CatalogCacheError, match="Не удалось прочитать"):
        load_catalog_cache("conditioners", _config(tmp_path), cache_dir)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.pop("saved_at"), "структуру"),
        (lambda payload: payload.update(version=2), "Версия"),
        (lambda payload: payload.update(profile="wreaths"), "другому профилю"),
        (lambda payload: payload.update(saved_at="not-a-date"), "неверную дату"),
        (
            lambda payload: payload.update(saved_at="2026-07-25T12:00:00"),
            "часовой пояс",
        ),
        (lambda payload: payload.update(rows={}), "списком"),
        (lambda payload: payload["rows"][0].pop("source"), "неверную схему"),
        (lambda payload: payload["rows"][0].update(key=""), "не имеет ключа"),
        (
            lambda payload: payload["rows"].append(deepcopy(payload["rows"][0])),
            "повторяется ключ",
        ),
        (
            lambda payload: payload["rows"][0].update(members={}),
            "должно быть списком",
        ),
        (
            lambda payload: payload["rows"][0]["members"][0].pop("cost"),
            "неверную схему",
        ),
    ],
)
def test_catalog_cache_rejects_incompatible_payload_shapes(
    tmp_path, mutate, message
):
    payload = _valid_payload(tmp_path)
    mutate(payload)
    _write_payload(tmp_path, payload)

    with pytest.raises(CatalogCacheError, match=message):
        load_catalog_cache("conditioners", _config(tmp_path), tmp_path / "cache")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source", 7, "строкой"),
        ("source", "x" * 32_769, "лимит длины"),
        ("source", "bad\0value", "NUL"),
        ("has_card", 1, "true/false"),
        ("stock_total", True, "целым числом"),
        ("stock_total", -1, "меньше допустимого"),
    ],
    ids=[
        "not-string",
        "too-long",
        "nul",
        "not-boolean",
        "boolean-is-not-integer",
        "negative",
    ],
)
def test_catalog_cache_rejects_unsafe_row_field_values(
    tmp_path, field, value, message
):
    payload = _valid_payload(tmp_path)
    payload["rows"][0][field] = value
    _write_payload(tmp_path, payload)

    with pytest.raises(CatalogCacheError, match=message):
        load_catalog_cache("conditioners", _config(tmp_path), tmp_path / "cache")


def test_catalog_cache_enforces_row_and_member_count_limits(
    tmp_path, monkeypatch
):
    import avito_studio.catalog_cache as cache

    payload = _valid_payload(tmp_path)
    monkeypatch.setattr(cache, "MAX_CACHE_ROWS", 0)
    _write_payload(tmp_path, payload)
    with pytest.raises(CatalogCacheError, match="слишком много строк"):
        load_catalog_cache("conditioners", _config(tmp_path), tmp_path / "cache")

    monkeypatch.setattr(cache, "MAX_CACHE_ROWS", 20_000)
    monkeypatch.setattr(cache, "MAX_MEMBERS_PER_ROW", 0)
    with pytest.raises(CatalogCacheError, match="Слишком много позиций"):
        load_catalog_cache("conditioners", _config(tmp_path), tmp_path / "cache")

    monkeypatch.setattr(cache, "MAX_MEMBERS_PER_ROW", 500)
    monkeypatch.setattr(cache, "MAX_TOTAL_MEMBERS", 0)
    with pytest.raises(CatalogCacheError, match="вложенных позиций"):
        load_catalog_cache("conditioners", _config(tmp_path), tmp_path / "cache")


def test_catalog_cache_rejects_duplicate_json_fields_and_invalid_utf8(
    tmp_path
):
    payload = _valid_payload(tmp_path)
    encoded = json.dumps(payload, ensure_ascii=False)
    path = cache_path("conditioners", tmp_path / "cache")
    path.write_text('{"version":1,' + encoded[1:], encoding="utf-8")
    with pytest.raises(CatalogCacheError, match="повторяется поле"):
        load_catalog_cache("conditioners", _config(tmp_path), tmp_path / "cache")

    path.write_bytes(b"\xff\xfe")
    with pytest.raises(CatalogCacheError, match="некорректный JSON"):
        load_catalog_cache("conditioners", _config(tmp_path), tmp_path / "cache")


def test_catalog_cache_roundtrips_optional_null_fields(tmp_path):
    member = replace(_row().members[0], current_price=None, cost=None)
    original = replace(_row(), avito_status=None, members=(member,))
    save_catalog_cache("conditioners", [original], tmp_path / "cache")

    loaded = load_catalog_cache(
        "conditioners", _config(tmp_path), tmp_path / "cache"
    )

    assert loaded[0].avito_status is None
    assert loaded[0].members[0].current_price is None
    assert loaded[0].members[0].cost is None
