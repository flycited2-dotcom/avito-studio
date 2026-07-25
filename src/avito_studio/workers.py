"""Фоновые операции (SSH — секунды/десятки секунд), чтобы не морозить UI-поток Qt."""
from __future__ import annotations

import logging
import subprocess

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


def _exception_message(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


class RefreshWorker(QObject):
    finished = Signal(list)     # list[CatalogRow]
    stale = Signal(list, str)   # read-only cached rows + причина недоступности сервера
    failed = Signal(str)

    def __init__(self, ssh, local_cfg, config_rel: str = "config/config.yaml",
                 local_catalog: bool = False, profile_key: str | None = None,
                 cache_dir=None):
        super().__init__()
        self.ssh = ssh
        self.local_cfg = local_cfg
        self.config_rel = config_rel   # YAML выбранного профиля (селектор в тулбаре)
        self.local_catalog = local_catalog
        self.profile_key = profile_key or (
            "wreaths"
            if config_rel == "profiles/wreaths.yaml"
            else "conditioners"
        )
        self.cache_dir = cache_dir

    def run(self):
        from avito_studio.catalog_service import fetch_catalog, fetch_local_catalog
        if self.local_catalog:
            try:
                rows = fetch_local_catalog(self.local_cfg.path, self.local_cfg)
            except Exception as exc:
                self.failed.emit(str(exc))
                return
            self.finished.emit(rows)
            return

        try:
            rows = fetch_catalog(self.ssh, self.local_cfg, self.config_rel)
        except (
            ConnectionError,
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            TimeoutError,
        ) as exc:
            from avito_studio.catalog_cache import (
                CatalogCacheError,
                load_catalog_cache,
            )

            try:
                cached_rows = load_catalog_cache(
                    self.profile_key,
                    self.local_cfg,
                    self.cache_dir,
                )
            except (CatalogCacheError, OSError) as cache_exc:
                self.failed.emit(
                    f"{_exception_message(exc)}\n"
                    f"Локальный кэш недоступен: {_exception_message(cache_exc)}"
                )
                return
            self.stale.emit(cached_rows, _exception_message(exc))
            return
        except Exception as exc:
            # Ошибки схемы/кода нельзя маскировать старым снимком: иначе несовместимое
            # обновление выглядело бы как обычный сетевой сбой.
            self.failed.emit(str(exc))
            return

        from avito_studio.catalog_cache import save_catalog_cache

        try:
            save_catalog_cache(self.profile_key, rows, self.cache_dir)
        except Exception as exc:
            # Свежий каталог полезнее старого кэша. Ошибка локального диска не должна
            # превращать успешное чтение сервера в ложную ошибку обновления.
            logger.warning(
                "Could not update catalog cache for profile %s: %s",
                self.profile_key,
                exc,
            )
        self.finished.emit(rows)


class DeployWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, bridge_root, ssh, config_path=None, local_feed: bool = False):
        super().__init__()
        self.bridge_root = bridge_root
        self.ssh = ssh
        self.config_path = config_path
        self.local_feed = local_feed

    def run(self):
        from avito_studio.deploy import deploy_and_rebuild, deploy_local_feed
        try:
            if self.local_feed:
                out = deploy_local_feed(self.config_path, self.ssh)
            else:
                out = deploy_and_rebuild(
                    self.bridge_root, self.ssh, self.config_path
                )
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished.emit(out)


class GenerateCardWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, ssh, series_key: str):
        super().__init__()
        self.ssh = ssh
        self.series_key = series_key

    def run(self):
        from avito_studio.card_generation import generate_card
        try:
            out = generate_card(self.ssh, self.series_key)
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished.emit(out)


class AvitoStatusWorker(QObject):
    finished = Signal(dict)   # {key: RowAvitoStatus}
    failed = Signal(str)

    def __init__(self, bridge_root, rows, profile_key: str = "conditioners"):
        super().__init__()
        self.bridge_root = bridge_root
        self.rows = rows
        self.profile_key = profile_key

    def run(self):
        from avito_studio.avito_status import fetch_statuses
        try:
            statuses = fetch_statuses(
                self.bridge_root, self.rows, self.profile_key
            )
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished.emit(statuses)


class PhotoUploadWorker(QObject):
    finished = Signal(str)   # публичный URL загруженного фото
    failed = Signal(str)

    def __init__(self, ssh, local_path, nc_code: str):
        super().__init__()
        self.ssh = ssh
        self.local_path = local_path
        self.nc_code = nc_code

    def run(self):
        from avito_studio.photo_upload import upload_manual_photo
        try:
            url = upload_manual_photo(self.ssh, self.local_path, self.nc_code)
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished.emit(url)


class CarverPhotoImportWorker(QObject):
    finished = Signal(int, int, int)
    failed = Signal(str)

    def __init__(self, ssh, config_path, rows, local_cfg):
        super().__init__()
        self.ssh = ssh
        self.config_path = config_path
        self.rows = rows
        self.local_cfg = local_cfg

    def run(self):
        from avito_studio.carver_photo_import import import_carver_photos
        try:
            found, added, preserved = import_carver_photos(
                self.ssh, self.config_path, self.rows, self.local_cfg)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(found, added, preserved)


class ContentCardImportWorker(QObject):
    finished = Signal(int, int, int)
    failed = Signal(str)

    def __init__(self, ssh, rows, local_cfg):
        super().__init__()
        self.ssh = ssh
        self.rows = rows
        self.local_cfg = local_cfg

    def run(self):
        from avito_studio.content_card_import import import_content_cards
        try:
            found, added, removed = import_content_cards(
                self.ssh, self.rows, self.local_cfg
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(found, added, removed)


class AppliancesPriceImportWorker(QObject):
    """Validate and install a local XLS price without publishing anything."""

    finished = Signal(str, int)
    failed = Signal(str)

    def __init__(self, source, bridge_root, local_cfg):
        super().__init__()
        self.source = source
        self.bridge_root = bridge_root
        self.local_cfg = local_cfg

    def run(self):
        from avito_studio.appliances_price_file import import_appliances_price

        try:
            target, count = import_appliances_price(
                self.source, self.bridge_root, self.local_cfg
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(str(target), count)


class _BlockingWaiter(QObject):
    """Приёмник результата worker'а, живущий в ГЛАВНОМ потоке: bound-методы QObject дают
    queued-доставку сигналов внутрь loop.exec(). Голые замыкания-функции выполнялись бы прямо
    в потоке worker'а — loop.quit() мог прозвучать ДО loop.exec() (no-op) и exec() вис навсегда."""

    def __init__(self, loop):
        super().__init__()
        self.loop = loop
        self.result: dict = {}

    def ok(self, url: str) -> None:
        self.result["url"] = url
        self.loop.quit()

    def fail(self, message: str) -> None:
        self.result["error"] = message
        self.loop.quit()


def upload_photo_blocking(ssh, local_path, nc_code: str, parent=None) -> str:
    """Грузит фото в QThread, но для вызывающего кода остаётся синхронным вызовом:
    локальный QEventLoop продолжает крутить UI (окно не «Не отвечает» на медленной сети),
    модальный прогресс-диалог показывает, что происходит. Ошибка — RuntimeError."""
    from PySide6.QtCore import QEventLoop, Qt
    from PySide6.QtWidgets import QProgressDialog
    progress = QProgressDialog("Загрузка фото на сервер…", "", 0, 0, parent)
    progress.setObjectName("dialogPage")
    progress.setMinimumWidth(420)
    progress.setCancelButton(None)   # отмена на полпути оставила бы файл на сервере без записи в config
    progress.setWindowTitle("Загрузка")
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(300)   # не мигать при мгновенной загрузке
    loop = QEventLoop()
    waiter = _BlockingWaiter(loop)
    thread = run_in_thread(PhotoUploadWorker(ssh, local_path, nc_code), waiter.ok, waiter.fail)
    loop.exec()
    thread.wait(5000)   # даём потоку штатно завершиться до выхода из функции
    progress.close()
    if "error" in waiter.result:
        raise RuntimeError(waiter.result["error"])
    return waiter.result["url"]


def run_in_thread(
    worker: QObject,
    on_finished,
    on_failed,
    *,
    on_stale=None,
    on_thread_finished=None,
    start: bool = True,
) -> QThread:
    """Поднимает worker.run() в QThread, коннектит сигналы, возвращает thread
    (вызывающий обязан держать ссылку, иначе Python/Qt соберёт поток раньше времени).

    Ссылка на worker хранится на самом thread (thread._worker) — иначе Python может
    собрать worker ДО того, как поток успеет вызвать run(), и сигнал никогда не долетит."""
    thread = QThread()
    thread._worker = worker   # держим worker живым, пока жив thread
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    stale_signal = getattr(worker, "stale", None)
    if on_stale is not None:
        if stale_signal is None:
            raise TypeError("Worker does not provide a stale signal")
        stale_signal.connect(on_stale)
        stale_signal.connect(thread.quit)
    # worker удаляем в ЕГО потоке, пока loop ещё жив (deleteLater в мёртвую очередь или
    # GC из главного потока при чужой аффинности спорадически валят процесс 0xC0000409;
    # эмпирика по вариантам паттерна — docs/qt-thread-teardown-flake.md в avito-studio)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    if on_stale is not None:
        stale_signal.connect(worker.deleteLater)
    if on_thread_finished is not None:
        thread.finished.connect(on_thread_finished)
    thread.finished.connect(thread.deleteLater)
    if start:
        thread.start()
    return thread
