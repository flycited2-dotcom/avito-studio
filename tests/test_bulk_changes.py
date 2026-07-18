from decimal import Decimal

import pytest

from avito_studio.bulk_changes import BulkRequest, build_bulk_preview
from avito_studio.catalog_service import CatalogMember, CatalogRow


def _row(key, *, selected=True, members=()):
    return CatalogRow(
        key=key,
        source="supplier",
        brand="Brand",
        series=key.upper(),
        sizes="—",
        stock_total=1,
        has_card=True,
        forced=any(member.forced for member in members),
        selected=selected,
        members=tuple(members),
    )


def _member(nc, price, cost=None, *, price_ok=True, forced=False):
    return CatalogMember(nc, price, cost, price_ok, forced)


def test_percent_change_uses_each_current_price_and_skips_below_cost():
    rows = [
        _row("a", members=[_member("A-1", 20000, 18000)]),
        _row("b", members=[_member("B-1", 10000, 9800)]),
    ]
    request = BulkRequest(
        target_keys=("a", "b"),
        price_mode="percent",
        price_value=Decimal("-5"),
    )

    preview = build_bulk_preview(rows, request)

    assert [(c.nc_code, c.old_price, c.new_price) for c in preview.price_changes] == [
        ("A-1", 20000, 19000),
    ]
    assert preview.skipped_below_cost == ("B-1",)


def test_amount_and_fixed_modes_round_to_integer_prices():
    row = _row("a", members=[_member("A-1", 101, 1)])

    amount = build_bulk_preview([row], BulkRequest(
        target_keys=("a",), price_mode="amount", price_value=Decimal("-5.5")))
    fixed = build_bulk_preview([row], BulkRequest(
        target_keys=("a",), price_mode="fixed", price_value=Decimal("99.5")))

    assert amount.price_changes[0].new_price == 96
    assert fixed.price_changes[0].new_price == 100


def test_reset_marks_regular_override_and_skips_forced_member():
    row = _row("a", members=[
        _member("A-1", 20000),
        _member("A-2", 30000, forced=True),
    ])

    preview = build_bulk_preview([row], BulkRequest(
        target_keys=("a",), price_mode="reset"))

    assert [(c.nc_code, c.new_price) for c in preview.price_changes] == [("A-1", None)]
    assert preview.skipped_forced_reset == ("A-2",)


def test_publication_change_only_lists_rows_that_really_change():
    rows = [_row("a", selected=True), _row("b", selected=False)]

    preview = build_bulk_preview(rows, BulkRequest(
        target_keys=("a", "b"), publication=False))

    assert [(c.key, c.old_selected, c.new_selected) for c in preview.series_changes] == [
        ("a", True, False),
    ]
    assert preview.price_changes == ()


def test_unknown_key_and_member_without_valid_price_are_reported():
    rows = [_row("a", members=[_member("A-1", None, price_ok=False)])]

    preview = build_bulk_preview(rows, BulkRequest(
        target_keys=("missing", "a"),
        price_mode="percent",
        price_value=Decimal("5"),
    ))

    assert preview.unknown_keys == ("missing",)
    assert preview.skipped_without_price == ("A-1",)


@pytest.mark.parametrize("mode,value", [
    ("percent", Decimal("-100")),
    ("percent", Decimal("10001")),
    ("fixed", Decimal("0")),
    ("amount", None),
    ("unknown", Decimal("1")),
])
def test_invalid_price_requests_are_rejected(mode, value):
    with pytest.raises(ValueError):
        build_bulk_preview([_row("a")], BulkRequest(
            target_keys=("a",), price_mode=mode, price_value=value))


def test_empty_target_selection_is_rejected():
    with pytest.raises(ValueError, match="товар"):
        build_bulk_preview([], BulkRequest(target_keys=()))
