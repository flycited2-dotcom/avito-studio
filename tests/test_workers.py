from pathlib import Path
from types import SimpleNamespace

import pytest

from avito_studio.catalog_cache import save_catalog_cache
from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig
from avito_studio.workers import (
    AppliancesPriceImportWorker,
    AvitoStatusWorker,
    CarverPhotoImportWorker,
    ContentCardImportWorker,
    DeployWorker,
    GenerateCardWorker,
    PhotoUploadWorker,
    RefreshWorker,
    _BlockingWaiter,
)


def test_deploy_worker_forwards_active_profile_config(monkeypatch):
    captured = {}
    finished = []

    def fake_deploy(bridge_root, ssh, config_path):
        captured["args"] = (bridge_root, ssh, config_path)
        return "published"

    from avito_studio import deploy

    monkeypatch.setattr(deploy, "deploy_and_rebuild", fake_deploy)
    ssh = object()
    worker = DeployWorker(
        "C:/bridge",
        ssh,
        config_path="C:/bridge/profiles/wreaths.yaml",
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert captured["args"] == (
        "C:/bridge",
        ssh,
        "C:/bridge/profiles/wreaths.yaml",
    )
    assert finished == ["published"]


@pytest.mark.parametrize("profile_key", ["conditioners", "wreaths"])
def test_avito_status_worker_forwards_profile_key(monkeypatch, profile_key):
    captured = {}
    finished = []

    def fake_fetch(bridge_root, rows, active_profile):
        captured["args"] = (bridge_root, rows, active_profile)
        return {"row": "status"}

    from avito_studio import avito_status as status

    monkeypatch.setattr(status, "fetch_statuses", fake_fetch)
    rows = [object()]
    worker = AvitoStatusWorker("C:/bridge", rows, profile_key)
    worker.finished.connect(finished.append)

    worker.run()

    assert captured["args"] == ("C:/bridge", rows, profile_key)
    assert finished == [{"row": "status"}]


class _CatalogSsh:
    def run(self, _command):
        return (
            '{"generated_at":"now","series":[{'
            '"key":"fresh","source":"breeze","brand":"Funai","series":"Sensei",'
            '"stock_total":2,"has_card":true,"forced":false,'
            '"members":[{"nc_code":"NC-1","btu_calc":7,"stock":2,'
            '"price":25000,"cost":20000,"price_ok":true,"forced":false}]}]}'
        )


class _UnavailableSsh:
    def run(self, _command):
        raise RuntimeError("database connection timed out")


def _local_config(tmp_path, selected="[]"):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"catalog:\n  selected_series: {selected}\n",
        encoding="utf-8",
    )
    return LocalConfig(config_path)


def test_refresh_worker_caches_successful_remote_catalog(tmp_path):
    cache_dir = tmp_path / "cache"
    finished = []
    stale = []
    worker = RefreshWorker(
        _CatalogSsh(),
        _local_config(tmp_path),
        profile_key="conditioners",
        cache_dir=cache_dir,
    )
    worker.finished.connect(finished.append)
    worker.stale.connect(lambda rows, reason: stale.append((rows, reason)))

    worker.run()

    assert [row.key for row in finished[0]] == ["fresh"]
    assert stale == []
    assert (cache_dir / "conditioners.json").is_file()


def test_refresh_worker_uses_cache_on_remote_availability_error(tmp_path):
    cache_dir = tmp_path / "cache"
    config = _local_config(tmp_path, selected='["__none__"]')
    cached = CatalogRow(
        key="cached",
        source="breeze",
        brand="Funai",
        series="Cached",
        sizes="—",
        stock_total=1,
        has_card=False,
        forced=False,
        selected=True,
    )
    save_catalog_cache("conditioners", [cached], cache_dir)
    stale = []
    failed = []
    worker = RefreshWorker(
        _UnavailableSsh(),
        config,
        profile_key="conditioners",
        cache_dir=cache_dir,
    )
    worker.stale.connect(lambda rows, reason: stale.append((rows, reason)))
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert stale[0][0][0].key == "cached"
    assert stale[0][0][0].selected is False
    assert stale[0][1] == "database connection timed out"


@pytest.mark.parametrize("corrupt", [False, True])
def test_refresh_worker_reports_remote_error_when_cache_unavailable(
    tmp_path, corrupt
):
    cache_dir = tmp_path / "cache"
    if corrupt:
        cache_dir.mkdir()
        (cache_dir / "conditioners.json").write_text("{broken", encoding="utf-8")
    failed = []
    stale = []
    worker = RefreshWorker(
        _UnavailableSsh(),
        _local_config(tmp_path),
        profile_key="conditioners",
        cache_dir=cache_dir,
    )
    worker.failed.connect(failed.append)
    worker.stale.connect(lambda rows, reason: stale.append((rows, reason)))

    worker.run()

    assert stale == []
    assert len(failed) == 1
    assert "database connection timed out" in failed[0]
    assert "Локальный кэш недоступен" in failed[0]


def test_refresh_worker_reads_local_catalog_without_ssh(monkeypatch, tmp_path):
    expected = [object()]
    calls = []
    monkeypatch.setattr(
        "avito_studio.catalog_service.fetch_local_catalog",
        lambda path, cfg: calls.append((path, cfg)) or expected,
    )
    config = _local_config(tmp_path)
    finished = []
    worker = RefreshWorker(
        _UnavailableSsh(),
        config,
        local_catalog=True,
        profile_key="appliances",
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == [expected]
    assert calls == [(config.path, config)]


def test_refresh_worker_reports_local_catalog_validation_error(
    monkeypatch, tmp_path
):
    def fail_local(*_args):
        raise ValueError("invalid local price")

    monkeypatch.setattr(
        "avito_studio.catalog_service.fetch_local_catalog", fail_local
    )
    failed = []
    worker = RefreshWorker(
        object(),
        _local_config(tmp_path),
        local_catalog=True,
    )
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == ["invalid local price"]


def test_refresh_worker_does_not_mask_programming_error_with_stale_cache(
    monkeypatch, tmp_path
):
    def fail_schema(*_args):
        raise ValueError("catalog schema changed")

    monkeypatch.setattr("avito_studio.catalog_service.fetch_catalog", fail_schema)
    failed = []
    stale = []
    worker = RefreshWorker(
        object(),
        _local_config(tmp_path),
        cache_dir=tmp_path / "cache",
    )
    worker.failed.connect(failed.append)
    worker.stale.connect(lambda *args: stale.append(args))

    worker.run()

    assert failed == ["catalog schema changed"]
    assert stale == []


def test_refresh_worker_keeps_fresh_rows_when_cache_write_fails(
    monkeypatch, tmp_path, caplog
):
    expected = [object()]
    monkeypatch.setattr(
        "avito_studio.catalog_service.fetch_catalog",
        lambda *_args: expected,
    )
    monkeypatch.setattr(
        "avito_studio.catalog_cache.save_catalog_cache",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    finished = []
    worker = RefreshWorker(object(), _local_config(tmp_path))
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == [expected]
    assert "disk full" in caplog.text


def test_deploy_worker_supports_local_feed_and_reports_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "avito_studio.deploy.deploy_local_feed",
        lambda config, ssh: calls.append((config, ssh)) or "local feed ready",
    )
    finished = []
    worker = DeployWorker(
        "unused",
        "offline-ssh",
        config_path="profiles/appliances.yaml",
        local_feed=True,
    )
    worker.finished.connect(finished.append)
    worker.run()
    assert finished == ["local feed ready"]
    assert calls == [("profiles/appliances.yaml", "offline-ssh")]

    monkeypatch.setattr(
        "avito_studio.deploy.deploy_local_feed",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("generation failed")),
    )
    failed = []
    worker = DeployWorker(
        "unused",
        object(),
        config_path="profiles/appliances.yaml",
        local_feed=True,
    )
    worker.failed.connect(failed.append)
    worker.run()
    assert failed == ["generation failed"]


def _worker_case(case):
    if case == "card":
        return (
            GenerateCardWorker(object(), "series-key"),
            "avito_studio.card_generation.generate_card",
            "card ready",
            ("card ready",),
        )
    if case == "status":
        return (
            AvitoStatusWorker(Path("bridge"), [object()], "wreaths"),
            "avito_studio.avito_status.fetch_statuses",
            {"series": object()},
            ({"series": object()},),
        )
    if case == "photo":
        return (
            PhotoUploadWorker(object(), Path("photo.jpg"), "NC-1"),
            "avito_studio.photo_upload.upload_manual_photo",
            "https://img.test/photo.jpg",
            ("https://img.test/photo.jpg",),
        )
    if case == "carver":
        return (
            CarverPhotoImportWorker(object(), Path("carver.yaml"), [], object()),
            "avito_studio.carver_photo_import.import_carver_photos",
            (3, 2, 1),
            (3, 2, 1),
        )
    if case == "content":
        return (
            ContentCardImportWorker(object(), [], object()),
            "avito_studio.content_card_import.import_content_cards",
            (4, 3, 1),
            (4, 3, 1),
        )
    if case == "appliances":
        return (
            AppliancesPriceImportWorker(
                Path("source.xls"), Path("bridge"), object()
            ),
            "avito_studio.appliances_price_file.import_appliances_price",
            (Path("installed.xls"), 128),
            ("installed.xls", 128),
        )
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case", ["card", "status", "photo", "carver", "content", "appliances"]
)
def test_operation_workers_emit_typed_success(monkeypatch, case):
    worker, target, result, expected = _worker_case(case)
    monkeypatch.setattr(target, lambda *_args: result)
    finished = []
    worker.finished.connect(lambda *args: finished.append(args))

    worker.run()

    if case == "status":
        assert list(finished[0][0]) == ["series"]
    else:
        assert finished == [expected]


@pytest.mark.parametrize(
    "case", ["card", "status", "photo", "carver", "content", "appliances"]
)
def test_operation_workers_forward_failures_without_false_success(
    monkeypatch, case
):
    worker, target, _result, _expected = _worker_case(case)

    def fail(*_args):
        raise RuntimeError(f"{case} failed")

    monkeypatch.setattr(target, fail)
    finished = []
    failed = []
    worker.finished.connect(lambda *args: finished.append(args))
    worker.failed.connect(failed.append)

    worker.run()

    assert finished == []
    assert failed == [f"{case} failed"]


def test_blocking_waiter_records_result_and_quits_loop():
    loop = SimpleNamespace(calls=0)
    loop.quit = lambda: setattr(loop, "calls", loop.calls + 1)
    waiter = _BlockingWaiter(loop)

    waiter.ok("https://img.test/ok.jpg")
    assert waiter.result == {"url": "https://img.test/ok.jpg"}
    waiter.fail("upload failed")

    assert waiter.result == {
        "url": "https://img.test/ok.jpg",
        "error": "upload failed",
    }
    assert loop.calls == 2
