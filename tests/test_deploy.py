import io
import json
import os
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace
import pytest
from avito_studio import description_store
import avito_studio.deploy as deploy_module

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


def _run_remote_python(script, *args):
    subprocess.run(
        [sys.executable, "-c", script, *(str(arg) for arg in args)],
        check=True,
        capture_output=True,
        text=True,
    )


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
    assert remote_path.startswith(
        "/opt/avito-bridge/runtime/studio-uploads/avito-studio-"
    )
    assert remote_path.endswith(".tgz")
    assert data.startswith(b"\x1f\x8b")             # gzip-магия — реально запаковано
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        assert "config/config.yaml" in tar.getnames()
        assert "description-patch/patch.json" in tar.getnames()
        assert not any(
            name.startswith("avito-descriptions/") for name in tar.getnames()
        )
    assert len(ssh.run_calls) == 2
    assert ssh.run_calls[0] == (
        "install -d -m 700 /opt/avito-bridge/runtime/studio-uploads"
    )
    assert "avito_bridge.profile_publish" in ssh.run_calls[1]
    assert "--config config/config.yaml" in ssh.run_calls[1]
    assert "systemctl" not in ssh.run_calls[1]


def test_deploy_includes_only_selected_profile_when_present(tmp_path):
    # правки YAML профилей (галочки венков) обязаны уезжать на сервер вместе с config/ —
    # иначе «Опубликовать» для второго бизнеса молча теряет изменения
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)
    (bridge_root / "profiles").mkdir(parents=True)
    (bridge_root / "profiles" / "wreaths.yaml").write_text("profile: {name: wreaths}\n", encoding="utf-8")

    ssh = FakeSsh()
    deploy_and_rebuild(
        bridge_root, ssh, bridge_root / "profiles" / "wreaths.yaml"
    )

    _, data = ssh.put_calls[0]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
    assert "profiles/wreaths.yaml" in names
    assert "config/config.yaml" not in names
    assert "--config profiles/wreaths.yaml" in ssh.run_calls[1]


def test_deploy_sends_only_selected_profiles_description_patch(tmp_path):
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text(
        "catalog: {}\n", encoding="utf-8"
    )
    (bridge_root / "profiles").mkdir()
    (bridge_root / "profiles" / "wreaths.yaml").write_text(
        "profile: {name: wreaths}\n", encoding="utf-8"
    )
    (bridge_root / "avito-descriptions").mkdir()
    (bridge_root / "avito-descriptions" / "manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    description_store.save_description(
        bridge_root, "conditioners-key", "Кондиционеры", "conditioners"
    )
    description_store.save_description(
        bridge_root, "wreaths-key", "Венки", "wreaths"
    )

    ssh = FakeSsh()
    deploy_and_rebuild(
        bridge_root, ssh, bridge_root / "profiles" / "wreaths.yaml"
    )

    with tarfile.open(
        fileobj=io.BytesIO(ssh.put_calls[0][1]), mode="r:gz"
    ) as bundle:
        patch = json.loads(
            bundle.extractfile("description-patch/patch.json")
            .read()
            .decode("utf-8")
        )
        names = bundle.getnames()
    assert patch["profile"] == "wreaths"
    assert set(patch["upserts"]) == {"wreaths-key"}
    assert "conditioners-key" not in patch["upserts"]
    assert (
        "description-patch/files/"
        + description_store.slugify("wreaths-key")
    ) in names
    assert (
        "description-patch/files/"
        + description_store.slugify("conditioners-key")
    ) not in names
    # Only the remotely confirmed profile is acknowledged.
    assert description_store.build_profile_patch(
        bridge_root, "wreaths"
    )["upserts"] == {}
    assert set(
        description_store.build_profile_patch(
            bridge_root, "conditioners"
        )["upserts"]
    ) == {"conditioners-key"}


def test_failed_deploy_keeps_description_patch_pending(tmp_path):
    class FailingSsh(FakeSsh):
        def run(self, cmd):
            self.run_calls.append(cmd)
            if "profile_publish" in cmd:
                raise RuntimeError("remote failed")
            return "ok\n"

    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text(
        "catalog: {}\n", encoding="utf-8"
    )
    (bridge_root / "avito-descriptions").mkdir()
    (bridge_root / "avito-descriptions" / "manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    description_store.save_description(
        bridge_root, "key", "Новый текст", "conditioners"
    )

    with pytest.raises(RuntimeError, match="remote failed"):
        deploy_and_rebuild(bridge_root, FailingSsh())
    assert set(
        description_store.build_profile_patch(
            bridge_root, "conditioners"
        )["upserts"]
    ) == {"key"}


def test_deploy_without_profiles_dir_still_works(tmp_path):
    # старый checkout без profiles/ (или кондиционерный-только) не должен ломать публикацию
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)

    ssh = FakeSsh()
    out = deploy_and_rebuild(bridge_root, ssh)
    assert out == "ok\n"


def test_deploy_rejects_config_outside_bridge_root(tmp_path):
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text(
        "catalog: {}\n", encoding="utf-8"
    )
    outside = tmp_path / "outside.yaml"
    outside.write_text("catalog: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="внутри avito-bridge"):
        deploy_and_rebuild(bridge_root, FakeSsh(), outside)


def test_deploy_local_feed_builds_and_uploads_profile_xml(tmp_path, monkeypatch):
    price = tmp_path / "carver.xlsx"
    price.write_bytes(b"not-read")
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    cfg = profiles / "carver.yaml"
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
    assert ssh.run_calls[0] == (
        "mkdir -p /opt/oasis/staticfiles /opt/avito-bridge/state"
    )
    assert "xml.etree.ElementTree" in ssh.run_calls[1]
    assert "flock -n /opt/avito-bridge/state/profile-publish.lock" in ssh.run_calls[1]
    assert "mv -f" in ssh.run_calls[1]
    assert "studio-backups/local-carver-" in ssh.run_calls[1]
    assert "transaction.json" in ssh.run_calls[1]
    assert '"status": "prepared"' in ssh.run_calls[1]
    assert '"committed"' in ssh.run_calls[1]
    assert '"rolled_back"' in ssh.run_calls[1]
    assert "completed[keep:]" in ssh.run_calls[1]
    assert "local-carver-" in ssh.run_calls[1]
    assert " 20" in ssh.run_calls[1]
    assert "|| true" in ssh.run_calls[1]
    assert "feed count drop" in ssh.run_calls[1]
    assert "/opt/oasis/staticfiles/avito-feed-carver.xml" in ssh.run_calls[1]
    remote_path, data = ssh.put_calls[0]
    assert remote_path.startswith(
        "/opt/oasis/staticfiles/.avito-feed-carver.xml."
    )
    assert remote_path.endswith(".tmp")
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


def test_validate_feed_rejects_duplicate_ids():
    ad = (
        b"<Ad><Id>same</Id><Title>x</Title><Description>x</Description>"
        b"<Price>1</Price><Images><Image url='https://example.test/x.jpg'/>"
        b"</Images></Ad>"
    )
    with pytest.raises(ValueError, match="повторяется Id"):
        validate_feed_xml(b"<Ads>" + ad + ad + b"</Ads>", expected_ads=2)


def test_deploy_local_feed_rejects_non_public_destination(tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    cfg = profiles / "carver.yaml"
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
    monkeypatch.setattr("avito_studio.deploy.fetch_profile_offers", lambda loaded: [])
    monkeypatch.setattr(
        "avito_studio.deploy.run_cycle",
        lambda *args, **kwargs: type("Result", (), {"offers_in": 0, "ads_built": 0, "skipped": 0})(),
    )

    with pytest.raises(ValueError, match="можно публиковать только"):
        deploy_local_feed(cfg, FakeSsh())


def test_deploy_local_feed_rejects_profile_filename_mismatch_before_source_access(
    tmp_path, monkeypatch
):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    cfg = profiles / "carver.yaml"
    cfg.write_text(
        "profile:\n"
        "  name: wreaths\n"
        "  source: carver_xlsx\n"
        "  grouping: per_item\n"
        "  public_feed_path: /opt/oasis/staticfiles/avito-feed-carver.xml\n"
        "  source_options: {path: ignored.xlsx}\n"
        "cities: []\n"
        "pricing: {rounding: none}\n"
        "feed: {}\n"
        "content: {}\n"
        "catalog: {}\n"
        "cards: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "avito_studio.deploy.fetch_profile_offers",
        lambda _cfg: pytest.fail("source must not be accessed"),
    )

    with pytest.raises(ValueError, match="profile.name='carver'"):
        deploy_local_feed(cfg, FakeSsh())


def test_deploy_local_feed_rechecks_installed_carver_price_age(
    tmp_path, monkeypatch
):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    cfg_path = profiles / "carver.yaml"
    cfg_path.write_text("profile: {name: carver}\n", encoding="utf-8")
    price = tmp_path / "runtime" / "carver" / "current.xlsx"
    price.parent.mkdir(parents=True)
    price.write_bytes(b"old supplier price")
    stale = time.time() - 91 * 24 * 60 * 60
    os.utime(price, (stale, stale))
    cfg = SimpleNamespace(
        profile_name="carver",
        public_feed_path="/opt/oasis/staticfiles/avito-feed-carver.xml",
        source_options={"path": "runtime/carver/current.xlsx"},
    )
    monkeypatch.setattr("avito_studio.deploy.load_config", lambda _path: cfg)
    monkeypatch.setattr(
        "avito_studio.deploy.fetch_profile_offers",
        lambda _cfg: pytest.fail("stale price must be rejected before parsing"),
    )

    with pytest.raises(ValueError, match="старше 90 дней"):
        deploy_local_feed(cfg_path, FakeSsh())


@pytest.mark.parametrize("had_previous", [True, False])
def test_local_publication_journal_recovers_crash_after_feed_replace(
    tmp_path, had_previous
):
    backup_root = tmp_path / "studio-backups"
    backup_dir = backup_root / "local-carver-crashed"
    public_feed = tmp_path / "public" / "avito-feed-carver.xml"
    public_feed.parent.mkdir()
    if had_previous:
        public_feed.write_text("last-good", encoding="utf-8")

    _run_remote_python(
        deploy_module._LOCAL_BACKUP_PREPARE_SCRIPT,
        backup_dir,
        public_feed,
    )
    # Simulate the durable state after atomic mv and before status=committed.
    public_feed.write_text("new-but-uncommitted", encoding="utf-8")
    _run_remote_python(
        deploy_module._LOCAL_BACKUP_RECOVERY_SCRIPT,
        backup_root,
        "local-carver-",
        public_feed,
    )

    if had_previous:
        assert public_feed.read_text(encoding="utf-8") == "last-good"
    else:
        assert not public_feed.exists()
    journal = json.loads(
        (backup_dir / "transaction.json").read_text(encoding="utf-8")
    )
    assert journal["status"] == "rolled_back"


def test_local_committed_publication_is_not_recovered(tmp_path):
    backup_root = tmp_path / "studio-backups"
    backup_dir = backup_root / "local-carver-complete"
    public_feed = tmp_path / "public" / "avito-feed-carver.xml"
    public_feed.parent.mkdir()
    public_feed.write_text("last-good", encoding="utf-8")
    _run_remote_python(
        deploy_module._LOCAL_BACKUP_PREPARE_SCRIPT,
        backup_dir,
        public_feed,
    )
    public_feed.write_text("committed", encoding="utf-8")
    _run_remote_python(
        deploy_module._LOCAL_BACKUP_COMMIT_SCRIPT,
        backup_dir,
        public_feed,
    )

    _run_remote_python(
        deploy_module._LOCAL_BACKUP_RECOVERY_SCRIPT,
        backup_root,
        "local-carver-",
        public_feed,
    )

    assert public_feed.read_text(encoding="utf-8") == "committed"
    journal = json.loads(
        (backup_dir / "transaction.json").read_text(encoding="utf-8")
    )
    assert journal["status"] == "committed"
