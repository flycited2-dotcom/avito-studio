import io
import tarfile
from pathlib import Path
import pytest

from avito_studio.deploy import deploy_and_rebuild, deploy_local_feed, validate_feed_xml


class FakeSsh:
    def __init__(self):
        self.put_calls = []
        self.run_calls = []

    def put(self, remote_path, data):
        self.put_calls.append((remote_path, data))

    def run(self, cmd):
        self.run_calls.append(cmd)
        return "ok\n"


def test_deploy_and_rebuild_packages_config_and_descriptions_and_runs_remote(tmp_path):
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)
    (bridge_root / "avito-descriptions" / "manifest.json").write_text("{}", encoding="utf-8")

    ssh = FakeSsh()
    out = deploy_and_rebuild(bridge_root, ssh)

    assert out == "ok\n"
    assert len(ssh.put_calls) == 1
    remote_path, data = ssh.put_calls[0]
    assert remote_path == "/tmp/studio_deploy.tgz"
    assert data.startswith(b"\x1f\x8b")             # gzip-магия — реально запаковано
    assert len(ssh.run_calls) == 1
    assert "cards_run" in ssh.run_calls[0]
    assert "systemctl start avito-bridge.service" in ssh.run_calls[0]


def test_deploy_includes_profiles_dir_when_present(tmp_path):
    # правки YAML профилей (галочки венков) обязаны уезжать на сервер вместе с config/ —
    # иначе «Опубликовать» для второго бизнеса молча теряет изменения
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)
    (bridge_root / "profiles").mkdir(parents=True)
    (bridge_root / "profiles" / "wreaths.yaml").write_text("profile: {name: wreaths}\n", encoding="utf-8")

    ssh = FakeSsh()
    deploy_and_rebuild(bridge_root, ssh)

    _, data = ssh.put_calls[0]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
    assert "profiles/wreaths.yaml" in names


def test_deploy_without_profiles_dir_still_works(tmp_path):
    # старый checkout без profiles/ (или кондиционерный-только) не должен ломать публикацию
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)

    ssh = FakeSsh()
    out = deploy_and_rebuild(bridge_root, ssh)
    assert out == "ok\n"


def test_deploy_local_feed_builds_and_uploads_profile_xml(tmp_path, monkeypatch):
    price = tmp_path / "carver.xlsx"
    price.write_bytes(b"not-read")
    cfg = tmp_path / "carver.yaml"
    cfg.write_text(
        "profile:\n"
        "  name: carver\n"
        "  source: carver_xlsx\n"
        "  grouping: per_item\n"
        "  feed_path: feed_out/carver.xml\n"
        "  public_feed_path: /opt/oasis/staticfiles/avito-feed-carver.xml\n"
        f"  source_options: {{path: '{price.as_posix()}'}}\n"
        "cities:\n"
        "  - {id: simferopol, name: Симферополь, avito_location: Симферополь}\n"
        "pricing: {rounding: none, default_markup_pct: 10, min_margin_abs: 0, rules: []}\n"
        "feed:\n"
        "  max_active_ads: 10\n"
        "  base_tags: {Category: 'Для дома и дачи', GoodsType: 'Садовая техника', Condition: 'Новое'}\n"
        "content: {title_max: 50, description_max: 7000, stop_words: [], description_attr: desc_long}\n"
        "catalog:\n"
        "  manual_photos: {PPG-1900IS: 'https://example.test/ppg.jpg'}\n"
        "  selected_series: ['carver_xlsx|item|carver:PPG-1900IS']\n"
        "cards: {enabled: false}\n",
        encoding="utf-8",
    )
    import avito_bridge.ingest.carver_xlsx as carver
    monkeypatch.setattr(carver, "parse_carver_xlsx", lambda path: [{
        "row": 4, "article": "PPG-1900IS", "model": "PPG-1900IS",
        "name": "Генератор CARVER PPG-1900IS", "characteristics": "Мощность: 2 кВт",
        "price": 10000.0, "kind": "generator",
    }])

    ssh = FakeSsh()
    out = deploy_local_feed(cfg, ssh)

    assert "profile=carver" in out
    assert "ads_built=1" in out
    assert ssh.run_calls[0] == "mkdir -p /opt/oasis/staticfiles"
    assert "xml.etree.ElementTree" in ssh.run_calls[1]
    assert "&& mv -f" in ssh.run_calls[1]
    assert "/opt/oasis/staticfiles/avito-feed-carver.xml" in ssh.run_calls[1]
    remote_path, data = ssh.put_calls[0]
    assert remote_path == "/opt/oasis/staticfiles/.avito-feed-carver.xml.tmp"
    assert b"<Ads" in data and b"PPG-1900IS" in data


def test_validate_feed_rejects_zero_ads():
    with pytest.raises(ValueError, match="объявлен"):
        validate_feed_xml(b"<Ads></Ads>", expected_ads=1)


def test_validate_feed_rejects_missing_required_field():
    data = (
        b'<Ads><Ad><Id>x</Id><Title>x</Title><Description>x</Description>'
        b'<Price>1</Price><Images /></Ad></Ads>'
    )
    with pytest.raises(ValueError, match="Images/Image"):
        validate_feed_xml(data, expected_ads=1)


def test_deploy_local_feed_rejects_non_public_destination(tmp_path, monkeypatch):
    cfg = tmp_path / "unsafe.yaml"
    cfg.write_text(
        "profile:\n"
        "  name: carver\n"
        "  source: carver_xlsx\n"
        "  grouping: per_item\n"
        "  public_feed_path: /tmp/carver.xml\n"
        "  source_options: {path: ignored.xlsx}\n"
        "cities: []\n"
        "pricing: {rounding: none}\n"
        "feed: {}\n"
        "content: {}\n"
        "catalog: {}\n"
        "cards: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("avito_studio.deploy.get_source", lambda source: lambda loaded: [])
    monkeypatch.setattr(
        "avito_studio.deploy.run_cycle",
        lambda *args, **kwargs: type("Result", (), {"offers_in": 0, "ads_built": 0, "skipped": 0})(),
    )

    with pytest.raises(ValueError, match="публичного фида"):
        deploy_local_feed(cfg, FakeSsh())
