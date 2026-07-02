import json
from avito_studio.publish_summary import save_snapshot, summarize_changes

CFG_V1 = """\
catalog:
  force_include:
    "НС-1": { price: 18990, series: "ACE-07" }
  manual_price_override:
    "НС-2": 22990
  manual_photos: {}
  manual_card_brief: {}
  selected_series:
    - "breeze|funai|sensei 2.0"
"""

CFG_V2 = """\
catalog:
  force_include:
    "НС-1": { price: 19990, series: "ACE-07" }
    "НС-9": { price: 30990 }
  manual_price_override:
    "НС-3": 15990
  manual_photos:
    "НС-9": "https://x/9.jpg"
  manual_card_brief:
    "НС-9": "Тихий"
  selected_series:
    - "daichi|midea|изи"
"""


def _bridge(tmp_path, cfg_text):
    root = tmp_path / "bridge"
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "config.yaml").write_text(cfg_text, encoding="utf-8")
    desc = root / "avito-descriptions"
    desc.mkdir(exist_ok=True)
    (desc / "manifest.json").write_text("{}", encoding="utf-8")
    return root


def test_no_snapshot_returns_none(tmp_path):
    root = _bridge(tmp_path, CFG_V1)
    assert summarize_changes(root, tmp_path / "snap") is None


def test_no_changes_returns_empty_list(tmp_path):
    root = _bridge(tmp_path, CFG_V1)
    save_snapshot(root, tmp_path / "snap")
    assert summarize_changes(root, tmp_path / "snap") == []


def test_summarizes_every_kind_of_change(tmp_path):
    root = _bridge(tmp_path, CFG_V1)
    save_snapshot(root, tmp_path / "snap")
    (root / "config" / "config.yaml").write_text(CFG_V2, encoding="utf-8")
    lines = summarize_changes(root, tmp_path / "snap")
    text = "\n".join(lines)
    assert "включена публикация: daichi|midea|изи" in text
    assert "выключена публикация: breeze|funai|sensei 2.0" in text
    assert "новый товар вручную: НС-9 — 30990 ₽" in text
    assert "цена (под заказ) НС-1: 18990 → 19990 ₽" in text
    assert "ручная цена НС-3: 15990 ₽" in text
    assert "цена НС-2: возврат к авторасчёту" in text
    assert "новое фото: НС-9" in text
    assert "УТП карточки: НС-9" in text


def test_summarizes_description_changes(tmp_path):
    root = _bridge(tmp_path, CFG_V1)
    save_snapshot(root, tmp_path / "snap")
    desc = root / "avito-descriptions"
    (desc / "studio-funai.txt").write_text("Новый текст\n", encoding="utf-8")
    (desc / "manifest.json").write_text(
        json.dumps({"breeze|funai|sensei 2.0": "studio-funai.txt"}), encoding="utf-8")
    lines = summarize_changes(root, tmp_path / "snap")
    assert lines == ["описание объявления: breeze|funai|sensei 2.0"]


def test_snapshot_after_publish_resets_baseline(tmp_path):
    root = _bridge(tmp_path, CFG_V1)
    save_snapshot(root, tmp_path / "snap")
    (root / "config" / "config.yaml").write_text(CFG_V2, encoding="utf-8")
    save_snapshot(root, tmp_path / "snap")   # «опубликовали» V2
    assert summarize_changes(root, tmp_path / "snap") == []
