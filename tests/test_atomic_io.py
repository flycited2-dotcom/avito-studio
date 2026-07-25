import json

import pytest

from avito_studio import atomic_io


def test_atomic_write_text_replaces_complete_file_and_cleans_temp(tmp_path):
    path = tmp_path / "settings.txt"
    path.write_text("old", encoding="utf-8")

    atomic_io.atomic_write_text(path, "new\nvalue\n")

    assert path.read_text(encoding="utf-8") == "new\nvalue\n"
    assert list(tmp_path.glob(".settings.txt.*.tmp")) == []


def test_atomic_write_keeps_old_file_when_writer_fails(tmp_path):
    path = tmp_path / "settings.txt"
    path.write_text("old", encoding="utf-8")

    def fail_after_partial_write(stream):
        stream.write("partial")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        atomic_io.atomic_write(path, fail_after_partial_write)

    assert path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".settings.txt.*.tmp")) == []


def test_atomic_write_keeps_old_file_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "settings.txt"
    path.write_text("old", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise PermissionError("locked")

    monkeypatch.setattr(atomic_io.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="locked"):
        atomic_io.atomic_write_text(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".settings.txt.*.tmp")) == []


def test_atomic_write_json_is_utf8_and_valid(tmp_path):
    path = tmp_path / "manifest.json"

    atomic_io.atomic_write_json(path, {"серия": "Изи"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"серия": "Изи"}
    assert path.read_bytes().endswith(b"\n")
