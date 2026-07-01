from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Signal, Qt, QSortFilterProxyModel
from PySide6.QtWidgets import (QMainWindow, QTableView, QToolBar, QLineEdit,
                               QStatusBar, QWidget, QVBoxLayout)
from avito_studio.local_config import LocalConfig
from avito_studio.catalog_table_model import CatalogTableModel
from avito_studio.workers import RefreshWorker, DeployWorker, run_in_thread


class MainWindow(QMainWindow):
    refresh_done = Signal()
    deploy_done = Signal()

    def __init__(self, bridge_root: Path, config_path: Path, ssh):
        super().__init__()
        self.setWindowTitle("Avito Content Studio")
        self.bridge_root = Path(bridge_root)
        self.config_path = Path(config_path)
        self.ssh = ssh
        self.local_cfg = LocalConfig(self.config_path)
        self.model = CatalogTableModel([])
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)   # искать по всем колонкам

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.doubleClicked.connect(self._open_edit_dialog)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по бренду/серии…")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

        toolbar = QToolBar()
        toolbar.addAction("Обновить", self.refresh)
        toolbar.addAction("Опубликовать изменения", self.publish)
        self.addToolBar(toolbar)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.search)
        layout.addWidget(self.table)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self._threads = []   # держим ссылки, чтобы QThread не собрался раньше времени

    def refresh(self):
        self.statusBar().showMessage("Обновление каталога с сервера…")
        worker = RefreshWorker(self.ssh, self.local_cfg)
        self._threads.append(run_in_thread(worker, self._on_refresh_ok, self._on_error))

    def _on_refresh_ok(self, rows):
        self.model = CatalogTableModel(rows)
        self.proxy.setSourceModel(self.model)
        self.statusBar().showMessage(f"Загружено серий: {len(rows)}", 5000)
        self.refresh_done.emit()

    def save_local_selection(self):
        for row in self.model.rows:
            if row.key in self.model.dirty_keys:
                self.local_cfg.set_selected(row.key, row.selected)
        self.local_cfg.save()
        self.model.dirty_keys.clear()

    def publish(self):
        self.save_local_selection()
        self.statusBar().showMessage("Публикация на сервер (может занять до минуты)…")
        worker = DeployWorker(self.bridge_root, self.ssh)
        self._threads.append(run_in_thread(worker, self._on_publish_ok, self._on_error))

    def _on_publish_ok(self, output: str):
        self.statusBar().showMessage("Опубликовано. Сервер пересобирает фид.", 8000)
        self.deploy_done.emit()

    def _on_error(self, message: str):
        self.statusBar().showMessage(f"Ошибка: {message}", 10000)

    def _open_edit_dialog(self, proxy_index) -> None:
        from avito_studio.edit_dialog import EditSeriesDialog
        source_index = self.proxy.mapToSource(proxy_index)
        row = self.model.rows[source_index.row()]
        dlg = EditSeriesDialog(row, self.bridge_root, self.local_cfg, self.ssh, parent=self)
        if dlg.exec():
            dlg.save()
            top_left = self.model.index(source_index.row(), 0)
            bottom_right = self.model.index(source_index.row(), self.model.columnCount() - 1)
            self.model.dataChanged.emit(top_left, bottom_right)
            self.statusBar().showMessage("Серия сохранена локально (для сервера — «Опубликовать»)", 5000)
