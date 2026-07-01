from avito_studio.local_config import LocalConfig

FIXTURE = """\
# комментарий, который должен выжить
cities:
  - { id: "simferopol", name: "Симферополь", avito_location: "Крым" }
pricing:
  default_markup_pct: 5
catalog:
  force_include:
    "НС-1": { price: 18990, series: "ACE-07" }
  manual_photos:
    "НС-2": "https://x/2.jpg"
  selected_series:
    - "breeze|funai|sensei 2.0"
    - "daichi|midea|изи"
"""


def _write(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(FIXTURE, encoding="utf-8")
    return p


def test_is_selected_reflects_yaml(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert cfg.is_selected("breeze|funai|sensei 2.0") is True
    assert cfg.is_selected("nope|not|there") is False


def test_set_selected_true_adds_and_saves(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("rusklimat|ballu|tessey dc", True)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.is_selected("rusklimat|ballu|tessey dc") is True
    assert "комментарий, который должен выжить" in path.read_text(encoding="utf-8")


def test_set_selected_false_removes_and_is_idempotent(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("daichi|midea|изи", False)
    cfg.set_selected("daichi|midea|изи", False)   # повторный вызов не должен падать
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.is_selected("daichi|midea|изи") is False
    assert reloaded.is_selected("breeze|funai|sensei 2.0") is True   # остальное не тронуто


def test_selected_series_lists_all(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert set(cfg.selected_series()) == {"breeze|funai|sensei 2.0", "daichi|midea|изи"}


def test_save_preserves_sequence_indentation_style(tmp_path):
    """Без явного yaml.indent(...) ruamel сбрасывает отступ списка при КАЖДОМ save() —
    даёт огромный шумный diff, даже когда правишь одну строку. Список должен остаться
    с отступом в 4 пробела (стиль, уже используемый в реальном config.yaml)."""
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("new|entry|x", True)
    cfg.save()
    text = path.read_text(encoding="utf-8")
    assert '    - "breeze|funai|sensei 2.0"' in text
    assert '    - "new|entry|x"' in text


def test_get_force_price_reads_existing_entry(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert cfg.get_force_price("НС-1") == 18990
    assert cfg.get_force_price("НС-999") is None


def test_set_force_price_updates_existing_entry_and_saves(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_force_price("НС-1", 20990)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-1") == 20990
    assert "ACE-07" in path.read_text(encoding="utf-8")   # серия у записи не потерялась


def test_manual_photo_get_set_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    assert cfg.get_manual_photo("НС-9") is None
    cfg.set_manual_photo("НС-9", "https://splithome.ru/static/manual-photos/НС-9.jpg")
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_manual_photo("НС-9") == "https://splithome.ru/static/manual-photos/НС-9.jpg"
    assert reloaded.get_manual_photo("НС-2") == "https://x/2.jpg"   # старая запись не потерялась


def test_add_force_include_new_entry_with_series(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.add_force_include("НС-777", 15990, series="Тестовая серия")
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-777") == 15990
    text = path.read_text(encoding="utf-8")
    assert "НС-777" in text and "Тестовая серия" in text
    assert "НС-1" in text and "ACE-07" in text   # старая запись не потерялась


def test_add_force_include_without_series(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.add_force_include("НС-778", 9990)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-778") == 9990


# Реальный config.yaml: комментарий про manual_photos стоит СРАЗУ после последней записи
# force_include без пустой строки. ruamel склеивает такой комментарий с последним ключом —
# добавление в конец мапы (обычным присваиванием) "раздвигает" склейку и комментарий уезжает
# ВНУТРЬ force_include (перед новой записью, хотя семантически он про manual_photos).
FIXTURE_TRAILING_COMMENT = """\
catalog:
  force_include:
    "A": { price: 1, series: "s1" }   # comment A
    "B": { price: 2, series: "s2" }   # comment B
  # this comment belongs to manual_photos
  manual_photos:
    "X": "url"
"""


def test_add_force_include_does_not_disturb_trailing_comment_of_next_section(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_TRAILING_COMMENT, encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.add_force_include("C", 3, series="s3")
    cfg.save()
    text = path.read_text(encoding="utf-8")
    # комментарий должен остаться НЕПОСРЕДСТВЕННО перед "manual_photos:", а не между
    # force_include-записями
    assert "  # this comment belongs to manual_photos\n  manual_photos:" in text


def test_manual_price_get_set_remove_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    assert cfg.get_manual_price("НС-5") is None
    cfg.set_manual_price("НС-5", 24990)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_manual_price("НС-5") == 24990
    reloaded.remove_manual_price("НС-5")
    reloaded.save()
    assert LocalConfig(path).get_manual_price("НС-5") is None


def test_remove_manual_price_is_idempotent_when_absent(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.remove_manual_price("НС-999")   # не должно падать, даже если секции ещё нет
    cfg.save()


def test_set_manual_price_new_entry_quoted_and_does_not_disturb_trailing_comment(tmp_path):
    """Тот же сценарий, что у add_force_include: manual_price_override — совсем новая секция,
    добавляется ПОСЛЕ selected_series, перед которым в реальном config.yaml (0-й отступ, как у
    самого cards:) стоит комментарий про следующий раздел (cards:). Ключ должен быть в кавычках,
    а комментарий — не сдвинут внутрь catalog."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalog:\n"
        "  selected_series:\n"
        "    - \"a|b|c\"\n"
        "# this comment belongs to cards\n"
        "cards:\n"
        "  enabled: true\n",
        encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.set_manual_price("НС-42", 24990)
    cfg.save()
    text = path.read_text(encoding="utf-8")
    assert '"НС-42": 24990' in text
    assert "# this comment belongs to cards\ncards:" in text


def test_card_brief_get_set_remove_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    assert cfg.get_card_brief("НС-2") is None
    cfg.set_card_brief("НС-2", "Тихий, мощный, Wi-Fi")
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_card_brief("НС-2") == "Тихий, мощный, Wi-Fi"
    reloaded.remove_card_brief("НС-2")
    reloaded.save()
    assert LocalConfig(path).get_card_brief("НС-2") is None


def test_card_brief_new_entry_does_not_disturb_trailing_comment(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalog:\n"
        "  selected_series:\n"
        "    - \"a|b|c\"\n"
        "# this comment belongs to cards\n"
        "cards:\n"
        "  enabled: true\n",
        encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.set_card_brief("НС-42", "Компактный, тихий")
    cfg.save()
    text = path.read_text(encoding="utf-8")
    assert '"НС-42": "Компактный, тихий"' in text
    assert "# this comment belongs to cards\ncards:" in text
