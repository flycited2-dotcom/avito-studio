from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Signal, Qt, QSortFilterProxyModel
from PySide6.QtWidgets import (QMainWindow, QTableView, QToolBar, QLineEdit, QStyle,
                               QStatusBar, QWidget, QVBoxLayout, QMessageBox, QHeaderView,
                               QAbstractItemView)
from avito_studio.local_config import LocalConfig
from avito_studio.catalog_table_model import CatalogTableModel
from avito_studio.workers import RefreshWorker, DeployWorker, AvitoStatusWorker, run_in_thread


class MainWindow(QMainWindow):
    refresh_done = Signal()
    deploy_done = Signal()
    publish_failed = Signal(str)

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
        self.proxy.setSortRole(Qt.UserRole)  # числовая сортировка цены/остатка (см. модель)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.doubleClicked.connect(self._open_edit_dialog)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # чекбокс кликается и так
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(CatalogTableModel.COL_SERIES, QHeaderView.Stretch)
        header.setSortIndicatorShown(True)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по бренду/серии…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        style = self.style()
        act_refresh = toolbar.addAction(style.standardIcon(QStyle.SP_BrowserReload),
                                        "Обновить", self.refresh)
        act_publish = toolbar.addAction(style.standardIcon(QStyle.SP_DialogApplyButton),
                                        "Опубликовать изменения", self.publish)
        toolbar.addSeparator()
        act_add = toolbar.addAction(style.standardIcon(QStyle.SP_FileDialogNewFolder),
                                    "Добавить товар вручную", self._open_add_forced_dialog)
        act_status = toolbar.addAction(style.standardIcon(QStyle.SP_MessageBoxInformation),
                                       "Обновить статус Avito", self._refresh_avito_status)
        # пока идёт фоновая операция — все действия выключены (повторный клик по «Опубликовать»
        # иначе запустил бы ВТОРОЙ параллельный деплой на боевой сервер)
        self._busy_actions = [act_refresh, act_publish, act_add, act_status]
        self.addToolBar(toolbar)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.search)
        layout.addWidget(self.table)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Нажмите «Обновить», чтобы загрузить каталог с сервера")

        self._threads = []   # держим ссылки, чтобы QThread не собрался раньше времени

    def _set_busy(self, busy: bool) -> None:
        for act in self._busy_actions:
            act.setEnabled(not busy)

    def _status(self, message: str, timeout: int = 0, error: bool = False) -> None:
        bar = self.statusBar()
        bar.setProperty("error", error)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.showMessage(message, timeout)

    def refresh(self):
        self._set_busy(True)
        self._status("Обновление каталога с сервера…")
        worker = RefreshWorker(self.ssh, self.local_cfg)
        self._threads.append(run_in_thread(worker, self._on_refresh_ok, self._on_error))

    def _on_refresh_ok(self, rows):
        self.model = CatalogTableModel(rows)
        self.proxy.setSourceModel(self.model)
        self._set_busy(False)
        published = sum(1 for r in rows if r.selected)
        self._status(f"Серий: {len(rows)} · публикуется: {published}")
        self.refresh_done.emit()

    def save_local_selection(self):
        for row in self.model.rows:
            if row.key in self.model.dirty_keys:
                self.local_cfg.set_selected(row.key, row.selected)
        self.local_cfg.save()
        self.model.dirty_keys.clear()

    def publish(self):
        reply = QMessageBox.question(
            self, "Опубликовать изменения?",
            "Локальные изменения (публикация серий, цены, фото, описания) уйдут на сервер и "
            "попадут в реальный фид Avito. Продолжить?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self.save_local_selection()
        self._set_busy(True)
        self._status("Публикация на сервер (может занять до минуты)…")
        worker = DeployWorker(self.bridge_root, self.ssh)
        self._threads.append(run_in_thread(worker, self._on_publish_ok, self._on_publish_error))

    def _on_publish_ok(self, output: str):
        self._set_busy(False)
        self._status("Опубликовано. Сервер пересобирает фид.", 8000)
        self.deploy_done.emit()

    def _on_publish_error(self, message: str):
        self._set_busy(False)
        self._status(f"Ошибка публикации: {message}", error=True)
        # модально: провал публикации нельзя показывать только строкой статуса —
        # пользователь решит, что изменения ушли на Avito, а они не ушли
        QMessageBox.critical(self, "Публикация не удалась",
                             f"Изменения НЕ попали на сервер.\n\nПричина: {message}")
        self.publish_failed.emit(message)

    def _on_error(self, message: str):
        self._set_busy(False)
        self._status(f"Ошибка: {message}", error=True)

    def _open_edit_dialog(self, proxy_index) -> None:
        from avito_studio.edit_dialog import EditSeriesDialog
        source_index = self.proxy.mapToSource(proxy_index)
        row = self.model.rows[source_index.row()]
        dlg = EditSeriesDialog(row, self.bridge_root, self.local_cfg, self.ssh, parent=self)
        if not dlg.exec():
            return
        try:
            dlg.save()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить изменения: {e}")
            return
        top_left = self.model.index(source_index.row(), 0)
        bottom_right = self.model.index(source_index.row(), self.model.columnCount() - 1)
        self.model.dataChanged.emit(top_left, bottom_right)
        self._status("Серия сохранена локально (для сервера — «Опубликовать»)", 5000)
        QMessageBox.information(self, "Сохранено",
                                "Серия сохранена локально.\nЧтобы изменения ушли на Avito — «Опубликовать изменения».")

    def _open_add_forced_dialog(self) -> None:
        from avito_studio.add_forced_dialog import AddForcedProductDialog
        dlg = AddForcedProductDialog(self.local_cfg, self.ssh, parent=self)
        if not dlg.exec():
            return
        try:
            dlg.save()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось добавить товар: {e}")
            return
        self._status("Товар добавлен локально — «Опубликовать изменения», чтобы он ушёл на Avito", 8000)
        QMessageBox.information(self, "Добавлено",
                                "Товар добавлен локально.\nНажмите «Обновить», затем «Опубликовать изменения», "
                                "чтобы он появился на Avito.")

    def _refresh_avito_status(self) -> None:
        self._set_busy(True)
        self._status("Запрашиваю статус на Avito…")
        worker = AvitoStatusWorker(self.bridge_root, list(self.model.rows))
        self._threads.append(run_in_thread(worker, self._on_avito_status_ok, self._on_error))

    def _on_avito_status_ok(self, statuses: dict) -> None:
        self._set_busy(False)
        for row in self.model.rows:
            st = statuses.get(row.key)
            row.avito_status = st.avito_status if st else None
        top_left = self.model.index(0, 0)
        bottom_right = self.model.index(self.model.rowCount() - 1, self.model.columnCount() - 1)
        self.model.dataChanged.emit(top_left, bottom_right)
        matched = sum(1 for s in statuses.values() if s.avito_status)
        self._status(f"Статус получен: {matched} из {len(statuses)} серий", 8000)
