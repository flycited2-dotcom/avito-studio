import json

import pytest

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
    assert manifest["daichi|midea|изи"] == description_store.slugify("daichi|midea|изи")


def test_new_filenames_are_collision_safe_and_bounded():
    first = description_store.slugify("brand|model a")
    second = description_store.slugify("brand/model-a")
    assert first != second
    assert first.endswith(".txt") and second.endswith(".txt")
    assert len(description_store.slugify("очень-" * 100)) < 120


def test_blank_description_removes_manifest_entry_and_file(tmp_path):
    root = _bridge_root(tmp_path)

    description_store.save_description(root, "breeze|funai|sensei 2.0", "  ")

    manifest = json.loads((root / "avito-descriptions" / "manifest.json").read_text(encoding="utf-8"))
    assert "breeze|funai|sensei 2.0" not in manifest
    assert not (root / "avito-descriptions" / "sel-funai-sensei.txt").exists()
    assert description_store.get_description(root, "breeze|funai|sensei 2.0") == ""


def test_delete_keeps_file_still_referenced_by_another_key(tmp_path):
    root = _bridge_root(tmp_path)
    manifest_path = root / "avito-descriptions" / "manifest.json"
    manifest_path.write_text(json.dumps({
        "first": "shared.txt",
        "second": "shared.txt",
    }), encoding="utf-8")
    (manifest_path.parent / "shared.txt").write_text("Общий текст", encoding="utf-8")

    assert description_store.delete_description(root, "first") is True
    assert (manifest_path.parent / "shared.txt").exists()
    assert description_store.get_description(root, "second") == "Общий текст"
    assert description_store.delete_description(root, "missing") is False


def test_manifest_failure_rolls_back_new_description_file(tmp_path, monkeypatch):
    root = _bridge_root(tmp_path)
    key = "new|series|x"
    expected_file = root / "avito-descriptions" / description_store.slugify(key)

    def fail_manifest(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(description_store, "atomic_write_json", fail_manifest)
    with pytest.raises(OSError, match="disk full"):
        description_store.save_description(root, key, "Новый текст")

    assert not expected_file.exists()
    assert description_store.get_description(root, key) == ""


def test_delete_manifest_failure_keeps_original_file_and_mapping(tmp_path, monkeypatch):
    root = _bridge_root(tmp_path)

    def fail_manifest(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(description_store, "atomic_write_json", fail_manifest)
    with pytest.raises(OSError, match="disk full"):
        description_store.delete_description(root, "breeze|funai|sensei 2.0")

    assert description_store.get_description(
        root, "breeze|funai|sensei 2.0") == "Старое описание Sensei"


def test_manifest_cannot_escape_descriptions_directory(tmp_path):
    root = _bridge_root(tmp_path)
    manifest_path = root / "avito-descriptions" / "manifest.json"
    manifest_path.write_text(json.dumps({"bad": "../outside.txt"}), encoding="utf-8")
    (root / "outside.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="пределы"):
        description_store.get_description(root, "bad")


def test_profile_patches_are_owned_and_isolated(tmp_path):
    root = _bridge_root(tmp_path)
    description_store.save_description(
        root, "ritualb2b|item|venok-1", "Текст венка", "wreaths"
    )

    conditioners = description_store.build_profile_patch(root, "conditioners")
    wreaths = description_store.build_profile_patch(root, "wreaths")

    assert set(conditioners["upserts"]) == {"breeze|funai|sensei 2.0"}
    assert conditioners["deletions"] == []
    assert set(wreaths["upserts"]) == {"ritualb2b|item|venok-1"}
    assert wreaths["deletions"] == []


def test_profile_delete_becomes_tombstone_and_removes_pending_upsert(tmp_path):
    root = _bridge_root(tmp_path)
    key = "ritualb2b|item|venok-1"
    description_store.save_description(root, key, "Текст венка", "wreaths")
    first = description_store.build_profile_patch(root, "wreaths")
    assert description_store.acknowledge_profile_patch(
        root, "wreaths", first
    ) is True

    assert description_store.delete_description(root, key, "wreaths") is True
    patch = description_store.build_profile_patch(root, "wreaths")
    assert patch["upserts"] == {}
    assert patch["deletions"] == [key]


def test_other_profile_cannot_overwrite_or_delete_owned_description(tmp_path):
    root = _bridge_root(tmp_path)
    key = "ritualb2b|item|venok-1"
    description_store.save_description(root, key, "Текст венка", "wreaths")

    with pytest.raises(ValueError, match="принадлежит профилю 'wreaths'"):
        description_store.save_description(root, key, "Чужая правка", "carver")
    with pytest.raises(ValueError, match="принадлежит профилю 'wreaths'"):
        description_store.delete_description(root, key, "carver")
    assert description_store.get_description(root, key) == "Текст венка"
    assert description_store.get_description(root, key, "carver") == ""
    assert description_store.get_description(root, key, "wreaths") == "Текст венка"


def test_acknowledge_does_not_drop_a_concurrent_edit(tmp_path):
    root = _bridge_root(tmp_path)
    key = "ritualb2b|item|venok-1"
    description_store.save_description(root, key, "Первая версия", "wreaths")
    sent = description_store.build_profile_patch(root, "wreaths")
    description_store.save_description(root, key, "Вторая версия", "wreaths")

    assert description_store.acknowledge_profile_patch(
        root, "wreaths", sent
    ) is False
    assert description_store.build_profile_patch(root, "wreaths")["upserts"] == {
        key: description_store.slugify(key)
    }


def test_shared_legacy_filename_is_split_before_profile_edit(tmp_path):
    root = _bridge_root(tmp_path)
    manifest = root / "avito-descriptions" / "manifest.json"
    manifest.write_text(
        json.dumps({"first": "shared.txt", "second": "shared.txt"}),
        encoding="utf-8",
    )
    (manifest.parent / "shared.txt").write_text("Общий текст", encoding="utf-8")

    description_store.save_description(
        root, "first", "Отдельный текст", "conditioners"
    )

    mapping = json.loads(manifest.read_text(encoding="utf-8"))
    assert mapping["first"] != "shared.txt"
    assert description_store.get_description(root, "first") == "Отдельный текст"
    assert description_store.get_description(root, "second") == "Общий текст"
