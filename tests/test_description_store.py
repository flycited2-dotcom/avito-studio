import json
from avito_studio import description_store


def _bridge_root(tmp_path):
    root = tmp_path / "avito-bridge"
    d = root / "avito-descriptions"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"breeze|funai|sensei 2.0": "sel-funai-sensei.txt"}, ensure_ascii=False),
        encoding="utf-8")
    (d / "sel-funai-sensei.txt").write_text("Старое описание Sensei", encoding="utf-8")
    return root


def test_get_description_reads_existing_file(tmp_path):
    root = _bridge_root(tmp_path)
    assert description_store.get_description(root, "breeze|funai|sensei 2.0") == "Старое описание Sensei"


def test_get_description_returns_empty_when_not_in_manifest(tmp_path):
    root = _bridge_root(tmp_path)
    assert description_store.get_description(root, "daichi|midea|изи") == ""


def test_save_description_overwrites_existing_file(tmp_path):
    root = _bridge_root(tmp_path)
    description_store.save_description(root, "breeze|funai|sensei 2.0", "Новый текст")
    assert description_store.get_description(root, "breeze|funai|sensei 2.0") == "Новый текст"
    manifest = json.loads((root / "avito-descriptions" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["breeze|funai|sensei 2.0"] == "sel-funai-sensei.txt"   # имя файла не поменялось


def test_save_description_creates_new_entry_for_unknown_series(tmp_path):
    root = _bridge_root(tmp_path)
    description_store.save_description(root, "daichi|midea|изи", "Описание Изи")
    assert description_store.get_description(root, "daichi|midea|изи") == "Описание Изи"
    manifest = json.loads((root / "avito-descriptions" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["daichi|midea|изи"] == "studio-daichi-midea-изи.txt"
