import json

import pytest

import avito_studio.publish_summary as publish_summary
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


def test_profile_snapshots_are_isolated_and_use_selected_yaml(tmp_path):
    root = _bridge(tmp_path, CFG_V1)
    (root / "profiles").mkdir()
    wreaths = root / "profiles" / "wreaths.yaml"
    wreaths.write_text(
        "profile: {name: wreaths}\n"
        "catalog: {selected_series: [wreath-a]}\n",
        encoding="utf-8",
    )
    save_snapshot(
        root, tmp_path / "snap", config_path=wreaths, profile_key="wreaths"
    )
    wreaths.write_text(
        "profile: {name: wreaths}\n"
        "catalog: {selected_series: [wreath-b]}\n",
        encoding="utf-8",
    )

    lines = summarize_changes(
        root, tmp_path / "snap", config_path=wreaths, profile_key="wreaths"
    )

    assert "включена публикация: wreath-b" in lines
    assert "выключена публикация: wreath-a" in lines
    assert summarize_changes(
        root,
        tmp_path / "snap",
        config_path=root / "config" / "config.yaml",
        profile_key="conditioners",
    ) is None


def test_summary_detects_changed_local_source_file(tmp_path):
    root = _bridge(tmp_path, CFG_V1)
    price = root / "data" / "price.xlsx"
    price.parent.mkdir()
    price.write_bytes(b"v1")
    profile = root / "profiles" / "carver.yaml"
    profile.parent.mkdir()
    profile.write_text(
        "profile:\n"
        "  name: carver\n"
        "  source_options: {path: data/price.xlsx}\n"
        "catalog: {}\n",
        encoding="utf-8",
    )
    save_snapshot(root, tmp_path / "snap", profile, "carver")
    price.write_bytes(b"v2")

    lines = summarize_changes(root, tmp_path / "snap", profile, "carver")

    assert "изменён файл-источник товаров/цен" in lines


def test_snapshot_keeps_only_backup_when_promotion_and_restore_both_fail(
    tmp_path, monkeypatch
):
    root = _bridge(tmp_path, CFG_V1)
    snapshot = tmp_path / "snap"
    save_snapshot(root, snapshot)
    (root / "config" / "config.yaml").write_text(CFG_V2, encoding="utf-8")
    real_replace = publish_summary.os.replace
    replace_calls = 0

    def fail_promotion_and_restore(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            return real_replace(source, destination)
        if replace_calls == 2:
            raise OSError("promotion failed")
        raise OSError("restore failed")

    monkeypatch.setattr(
        publish_summary.os, "replace", fail_promotion_and_restore
    )

    with pytest.raises(RuntimeError, match="Резервная копия сохранена"):
        save_snapshot(root, snapshot)

    backups = list(tmp_path.glob(".snap.*.backup"))
    assert len(backups) == 1
    assert (
        backups[0] / "config" / "config.yaml"
    ).read_text(encoding="utf-8") == CFG_V1
    assert not snapshot.exists()
