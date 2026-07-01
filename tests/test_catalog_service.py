import json
from avito_studio.catalog_service import fetch_catalog, CatalogRow
from avito_studio.local_config import LocalConfig

FIXTURE_CFG = """\
catalog:
  selected_series:
    - "breeze|funai|sensei 2.0"
"""

FAKE_JSON = json.dumps({
    "generated_at": "2026-07-01T00:00:00Z",
    "series": [
        {"key": "breeze|funai|sensei 2.0", "source": "breeze", "brand": "Funai",
         "series": "Sensei 2.0", "category_id": 2, "stock_total": 5, "has_card": True,
         "forced": False, "members": [{"nc_code": "НС-1", "btu_calc": 7, "stock": 2,
         "price": 25990, "price_ok": True, "forced": False},
         {"nc_code": "НС-2", "btu_calc": 9, "stock": 3, "price": 27990,
          "price_ok": True, "forced": False}]},
        {"key": "daichi|midea|изи", "source": "daichi", "brand": "Midea", "series": "Изи",
         "category_id": 2, "stock_total": 1, "has_card": False, "forced": False,
         "members": [{"nc_code": "НС-3", "btu_calc": 12, "stock": 1, "price": 19990,
                     "price_ok": True, "forced": False}]},
    ],
})


class FakeSsh:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def run(self, cmd):
        self.calls.append(cmd)
        return self.output


def test_fetch_catalog_merges_remote_json_with_local_selection(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(FIXTURE_CFG, encoding="utf-8")
    ssh = FakeSsh(FAKE_JSON)
    rows = fetch_catalog(ssh, LocalConfig(cfg_path))
    assert len(rows) == 2
    sensei = next(r for r in rows if r.key == "breeze|funai|sensei 2.0")
    assert sensei.selected is True
    assert sensei.brand == "Funai" and sensei.sizes == "7/9 тыс. BTU"
    assert sensei.stock_total == 5 and sensei.has_card is True
    izy = next(r for r in rows if r.key == "daichi|midea|изи")
    assert izy.selected is False
    assert len(ssh.calls) == 1
    assert "catalog_export" in ssh.calls[0]
    assert sensei.representative_nc == "НС-1"          # первый член = репрезентативный (младший размер)
    assert sensei.price_range == "25990–27990 ₽"
    assert izy.price_range == "19990 ₽"
