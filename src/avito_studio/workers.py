"""Фоновые операции (SSH — секунды/десятки секунд), чтобы не морозить UI-поток Qt."""
from __future__ import annotations
from PySide6.QtCore import QObject, QThread, Signal


class RefreshWorker(QObject):
    finished = Signal(list)     # list[CatalogRow]
    failed = Signal(str)

    def __init__(self, ssh, local_cfg):
        super().__init__()
        self.ssh = ssh
        self.local_cfg = local_cfg

    def run(self):
        from avito_studio.catalog_service import fetch_catalog
        try:
            rows = fetch_catalog(self.ssh, self.local_cfg)
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished.emit(rows)


class DeployWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, bridge_root, ssh):
        super().__init__()
        self.bridge_root = bridge_root
        self.ssh = ssh

    def run(self):
        from avito_studio.deploy import deploy_and_rebuild
        try:
            out = deploy_and_rebuild(self.bridge_root, self.ssh)
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished.emit(out)


def run_in_thread(worker: QObject, on_finished, on_failed) -> QThread:
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
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
