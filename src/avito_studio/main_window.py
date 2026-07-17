from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Signal, Qt, QSortFilterProxyModel
from PySide6.QtWidgets import (QMainWindow, QTableView, QToolBar, QLineEdit, QStyle,
                               QStatusBar, QWidget, QVBoxLayout, QHBoxLayout, QMessageBox,
                               QHeaderView, QAbstractItemView, QComboBox, QLabel, QFrame,
                               QPushButton, QToolButton, QStackedWidget, QSizePolicy,
                               QButtonGroup)
from avito_studio.local_config import LocalConfig
from avito_studio.profiles import PROFILES, Profile
from avito_studio.catalog_table_model import CatalogTableModel
from avito_studio.workers import (RefreshWorker, DeployWorker, AvitoStatusWorker,
                                  CarverPhotoImportWorker, run_in_thread)
from avito_studio import publish_summary


class MainWindow(QMainWindow):
    refresh_done = Signal()
    deploy_done = Signal()
    publish_failed = Signal(str)

    def __init__(self, bridge_root: Path, config_path: Path, ssh, snapshot_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle("Avito Content Studio")
        self.bridge_root = Path(bridge_root)
        self.config_path = Path(config_path)
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else publish_summary.DEFAULT_SNAPSHOT_DIR
        self.ssh = ssh
        # Профиль бизнеса (Кондиционеры/Венки…): стартуем с первого (кондиционеры), его YAML —
        # переданный config_path (в тестах/старых сборках он не обязан лежать в config/config.yaml).
        self.profile: Profile = PROFILES[0]
        self._initial_config_path = self.config_path
        self.local_cfg = LocalConfig(self.config_path)
        self.model = CatalogTableModel([])
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)   # искать по всем колонкам
        self.proxy.setSortRole(Qt.UserRole)  # числовая сортировка цены/остатка (см. модель)

        # Таблица остаётся единственным редактором каталога; новая оболочка только меняет навигацию.
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

        style = self.style()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(210)
        for p in PROFILES:
            self.profile_combo.addItem(p.label, p)
        # activated (а не currentIndexChanged): срабатывает только от пользователя —
        # программный revert индекса при ошибке не должен перезапускать переключение
        self.profile_combo.activated.connect(self._switch_profile)

        # Действия по-прежнему QAction: одна команда используется и на обзоре, и в каталоге.
        self.act_import_cards = self._action(
            style.standardIcon(QStyle.SP_DialogOpenButton),
            "Взять фото из Контент-завода", self._import_content_cards)
        act_refresh = self._action(style.standardIcon(QStyle.SP_BrowserReload),
                                   "Обновить каталог", self.refresh)
        self.act_publish = self._action(style.standardIcon(QStyle.SP_DialogApplyButton),
                                        "Опубликовать изменения", self.publish)
        act_add = self._action(style.standardIcon(QStyle.SP_FileDialogNewFolder),
                               "Добавить товар", self._open_add_forced_dialog)
        act_status = self._action(style.standardIcon(QStyle.SP_MessageBoxInformation),
                                  "Статусы Avito", self._refresh_avito_status)
        # пока идёт фоновая операция — все действия выключены (повторный клик по «Опубликовать»
        # иначе запустил бы ВТОРОЙ параллельный деплой на боевой сервер)
        self._busy_actions = [act_refresh, self.act_publish, act_add, act_status]
        self.act_import_cards.setEnabled(False)

        central = QWidget(objectName="appShell")
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_sidebar())

        workspace = QWidget(objectName="workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_header())

        self.pages = QStackedWidget(objectName="pages")
        self.pages.addWidget(self._build_overview_page(act_refresh))
        self.pages.addWidget(self._build_catalog_page(
            act_refresh, self.act_publish, act_add, act_status))
        workspace_layout.addWidget(self.pages, 1)
        shell.addWidget(workspace, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Нажмите «Обновить», чтобы загрузить каталог с сервера")

        self._threads = []   # держим ссылки, чтобы QThread не собрался раньше времени
        self._show_page(0)
        self._update_dashboard([])

    def _action(self, icon, text: str, slot):
        """Создать общее действие, пригодное для нескольких кнопок на разных страницах."""
        from PySide6.QtGui import QAction
        action = QAction(icon, text, self)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    @staticmethod
    def _label(text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        return label

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        badge = self._label("AS", "brandBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(46, 46)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand_text.addWidget(self._label("Avito Studio", "brandTitle"))
        brand_text.addWidget(self._label("Контент и публикация", "brandSubtitle"))
        brand.addWidget(badge)
        brand.addLayout(brand_text, 1)
        layout.addLayout(brand)
        layout.addSpacing(22)
        layout.addWidget(self._label("РАБОТА", "navSection"))

        self.nav_overview = self._nav_button("▦  Обзор", 0)
        self.nav_catalog = self._nav_button("▤  Каталог", 1)
        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        nav_group.addButton(self.nav_overview)
        nav_group.addButton(self.nav_catalog)
        layout.addWidget(self.nav_overview)
        layout.addWidget(self.nav_catalog)
        layout.addSpacing(14)
        layout.addWidget(self._label("ПРОФИЛИ", "navSection"))

        profile_hint = QFrame(objectName="sidebarHint")
        hint_layout = QVBoxLayout(profile_hint)
        hint_layout.setContentsMargins(12, 10, 12, 10)
        hint_layout.setSpacing(3)
        hint_layout.addWidget(self._label("Рабочие направления", "hintTitle"))
        hint_layout.addWidget(self._label(
            "Кондиционеры · Венки\nБытовая техника · CARVER", "hintText"))
        layout.addWidget(profile_hint)
        layout.addStretch(1)

        safety = QFrame(objectName="safetyCard")
        safety_layout = QVBoxLayout(safety)
        safety_layout.setContentsMargins(12, 10, 12, 10)
        safety_layout.setSpacing(3)
        safety_layout.addWidget(self._label("●  Публикация защищена", "safetyTitle"))
        safety_text = self._label(
            "Перед отправкой всегда показывается сводка изменений.", "safetyText")
        safety_text.setWordWrap(True)
        safety_layout.addWidget(safety_text)
        layout.addWidget(safety)
        return sidebar

    def _nav_button(self, text: str, page: int) -> QPushButton:
        button = QPushButton(text, objectName="navButton")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, p=page: self._show_page(p))
        return button

    def _build_header(self) -> QFrame:
        header = QFrame(objectName="topHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = self._label("Обзор", "pageTitle")
        self.page_subtitle = self._label("Каталог, фото и публикация под контролем", "pageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        layout.addLayout(titles, 1)
        profile_box = QVBoxLayout()
        profile_box.setSpacing(3)
        profile_box.addWidget(self._label("РАБОЧИЙ ПРОФИЛЬ", "profileLabel"))
        profile_box.addWidget(self.profile_combo)
        layout.addLayout(profile_box)
        return header

    def _build_overview_page(self, act_refresh) -> QWidget:
        page = QWidget(objectName="contentPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_total_value, card = self._stat_card("Серий в каталоге", "#2f80ed")
        stats.addWidget(card)
        self.stat_selected_value, card = self._stat_card("К публикации", "#19b7c6")
        stats.addWidget(card)
        self.stat_cards_value, card = self._stat_card("С готовыми фото", "#59c995")
        stats.addWidget(card)
        self.stat_issues_value, card = self._stat_card("Требуют внимания", "#f1ad44")
        stats.addWidget(card)
        layout.addLayout(stats)

        layout.addWidget(self._label("Быстрые действия", "sectionTitle"))
        actions = QHBoxLayout()
        actions.setSpacing(14)
        actions.addWidget(self._action_card(
            self.act_import_cards, "Фото и карточки", "Импорт готового контента без публикации"))
        actions.addWidget(self._action_card(
            act_refresh, "Обновить товары", "Цена, остаток, фото и статусы"))
        actions.addWidget(self._action_card(
            self.act_publish, "Опубликовать", "Проверка изменений перед отправкой"))
        layout.addLayout(actions)

        catalog_card = QFrame(objectName="panelCard")
        catalog_layout = QVBoxLayout(catalog_card)
        catalog_layout.setContentsMargins(20, 18, 20, 18)
        catalog_layout.setSpacing(7)
        catalog_layout.addWidget(self._label("Текущий каталог", "panelTitle"))
        self.overview_catalog_text = self._label(
            "Загрузите каталог, чтобы увидеть сводку по выбранному профилю.", "panelSubtitle")
        catalog_layout.addWidget(self.overview_catalog_text)
        open_catalog = QPushButton("Открыть каталог  →", objectName="primaryButton")
        open_catalog.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        open_catalog.clicked.connect(lambda: self._show_page(1))
        catalog_layout.addSpacing(8)
        catalog_layout.addWidget(open_catalog)
        layout.addWidget(catalog_card)
        layout.addStretch(1)
        return page

    def _stat_card(self, title: str, color: str) -> tuple[QLabel, QFrame]:
        card = QFrame(objectName="statCard")
        card.setStyleSheet(f"QFrame#statCard {{ border-top: 3px solid {color}; }}")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(5)
        layout.addWidget(self._label(title, "statTitle"))
        value = self._label("0", "statValue")
        layout.addWidget(value)
        layout.addWidget(self._label("по текущему профилю", "statCaption"))
        return value, card

    def _action_card(self, action, title: str, subtitle: str) -> QFrame:
        card = QFrame(objectName="actionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addWidget(self._label(title, "actionTitle"))
        layout.addWidget(self._label(subtitle, "actionSubtitle"))
        button = QToolButton(objectName="cardActionButton")
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addSpacing(4)
        layout.addWidget(button)
        return card

    def _build_catalog_page(self, act_refresh, act_publish, act_add, act_status) -> QWidget:
        page = QWidget(objectName="contentPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 20)
        layout.setSpacing(14)

        toolbar = QToolBar(objectName="catalogToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.addAction(self.act_import_cards)
        toolbar.addAction(act_refresh)
        toolbar.addAction(act_publish)
        toolbar.addSeparator()
        toolbar.addAction(act_add)
        toolbar.addAction(act_status)
        # Та же иерархия действий, что в карточках и диалогах.
        publish_button = toolbar.widgetForAction(act_publish)
        add_button = toolbar.widgetForAction(act_add)
        if publish_button:
            publish_button.setProperty("role", "primary")
        if add_button:
            add_button.setProperty("role", "secondary")
        layout.addWidget(toolbar)

        filters = QFrame(objectName="filterCard")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        self.search.setMinimumHeight(38)
        filter_layout.addWidget(self.search, 1)
        layout.addWidget(filters)

        table_card = QFrame(objectName="tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_heading = QFrame(objectName="tableHeading")
        heading_layout = QVBoxLayout(table_heading)
        heading_layout.setContentsMargins(16, 12, 16, 10)
        heading_layout.setSpacing(2)
        heading_layout.addWidget(self._label("Каталог", "panelTitle"))
        self.catalog_caption = self._label("Дважды нажмите строку, чтобы открыть карточку", "panelSubtitle")
        heading_layout.addWidget(self.catalog_caption)
        table_layout.addWidget(table_heading)
        table_layout.addWidget(self.table, 1)
        layout.addWidget(table_card, 1)
        return page

    def _show_page(self, index: int) -> None:
        titles = (
            ("Обзор", "Каталог, фото и публикация под контролем"),
            ("Каталог", "Редактирование серий, цен, фото и видимости"),
        )
        self.pages.setCurrentIndex(index)
        self.nav_overview.setChecked(index == 0)
        self.nav_catalog.setChecked(index == 1)
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])

    def _update_dashboard(self, rows) -> None:
        total = len(rows)
        selected = sum(1 for row in rows if row.selected)
        with_cards = sum(1 for row in rows if row.has_card)
        attention = sum(1 for row in rows if not row.has_card or row.stock_total <= 0)
        self.stat_total_value.setText(str(total))
        self.stat_selected_value.setText(str(selected))
        self.stat_cards_value.setText(str(with_cards))
        self.stat_issues_value.setText(str(attention))
        self.overview_catalog_text.setText(
            f"{self.profile.label}: {total} серий · выбрано {selected} · с фото {with_cards}.")
        self.catalog_caption.setText(
            f"{total} серий · выбрано для публикации {selected} · двойной клик открывает карточку")

    def closeEvent(self, event) -> None:
        # QThread, уничтоженный вместе с окном во время работы, роняет ВЕСЬ процесс
        # (Qt fatal «Destroyed while thread is still running») — дожидаемся фоновых потоков
        for t in self._threads:
            try:
                t.quit()
                t.wait(3000)
            except RuntimeError:
                pass   # поток уже завершился и удалён (deleteLater) — обёртка Python пережила C++
        super().closeEvent(event)

    def _set_busy(self, busy: bool) -> None:
        for act in self._busy_actions:
            act.setEnabled(not busy)
        self.profile_combo.setEnabled(not busy)   # смена профиля посреди публикации = каша путей
        self.act_publish.setEnabled(not busy and self.profile.publish_enabled)
        can_import = self.profile.key in {"appliances", "carver"}
        self.act_import_cards.setEnabled(not busy and can_import)
        self.act_import_cards.setText(
            "Взять фото из прайса" if self.profile.key == "carver"
            else "Взять фото из Контент-завода")
        if self.profile.publish_enabled:
            self.act_publish.setToolTip("")
        else:
            self.act_publish.setToolTip(self.profile.publish_block_reason)

    def _profile_config_path(self, profile: Profile) -> Path:
        if profile.key == PROFILES[0].key:
            return self._initial_config_path
        return self.bridge_root / profile.config_rel

    def _switch_profile(self, index: int) -> None:
        profile: Profile = self.profile_combo.itemData(index)
        if profile.key == self.profile.key:
            return
        path = self._profile_config_path(profile)
        try:
            new_cfg = LocalConfig(path)
        except OSError:
            # вернуть комбо на текущий профиль: выбор не состоялся, состояние не менялось
            self.profile_combo.setCurrentIndex(
                next(i for i, p in enumerate(PROFILES) if p.key == self.profile.key))
            QMessageBox.critical(self, "Профиль недоступен",
                                 f"Не найден YAML профиля «{profile.label}»:\n{path}\n\n"
                                 "Обновите checkout avito-bridge (ветка с профилями).")
            return
        self.save_local_selection()               # несохранённые галочки старого профиля — не терять
        self.profile = profile
        self.config_path = path
        self.local_cfg = new_cfg
        self.profile_combo.setCurrentIndex(index)  # при программном вызове комбо ещё не переставлен
        self._set_busy(False)
        self.refresh()

    def _status(self, message: str, timeout: int = 0, error: bool = False) -> None:
        bar = self.statusBar()
        bar.setProperty("error", error)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.showMessage(message, timeout)

    def refresh(self):
        self._set_busy(True)
        self._status("Обновление локального прайса…" if self.profile.local_catalog
                     else "Обновление каталога с сервера…")
        worker = RefreshWorker(self.ssh, self.local_cfg, self.profile.config_rel,
                               local_catalog=self.profile.local_catalog)
        self._threads.append(run_in_thread(worker, self._on_refresh_ok, self._on_error))

    def _on_refresh_ok(self, rows):
        self.model = CatalogTableModel(rows)
        self.proxy.setSourceModel(self.model)
        self._set_busy(False)
        published = sum(1 for r in rows if r.selected)
        self._update_dashboard(rows)
        self._status(f"Серий: {len(rows)} · публикуется: {published}")
        self.refresh_done.emit()

    def save_local_selection(self):
        for row in self.model.rows:
            if row.key in self.model.dirty_keys:
                self.local_cfg.set_selected(row.key, row.selected)
        self.local_cfg.save()
        self.model.dirty_keys.clear()

    def _publish_question(self) -> str:
        """Текст подтверждения: конкретная сводка изменений с прошлой публикации, если есть база."""
        changes = publish_summary.summarize_changes(self.bridge_root, self.snapshot_dir)
        if changes is None:   # первая публикация из студии — базы для сравнения ещё нет
            return ("Локальные изменения (публикация серий, цены, фото, описания) уйдут на сервер "
                    "и попадут в реальный фид Avito. Продолжить?")
        if not changes:
            return ("Изменений с прошлой публикации не найдено.\n"
                    "Всё равно отправить на сервер (фид пересоберётся)?")
        shown = changes[:15]
        rest = len(changes) - len(shown)
        lines = "\n".join(f"• {c}" for c in shown)
        if rest > 0:
            lines += f"\n…и ещё {rest}"
        return f"На сервер и в реальный фид Avito уйдут изменения:\n\n{lines}\n\nПродолжить?"

    def publish(self):
        if not self.profile.publish_enabled:
            QMessageBox.warning(self, "Публикация CARVER заблокирована",
                                self.profile.publish_block_reason)
            return
        # галочки «Публикуется» сохраняем локально ДО сводки — иначе их не будет в списке;
        # локальная запись безвредна (диалоги и так пишут локально, публикация — отдельный шаг)
        self.save_local_selection()
        reply = QMessageBox.question(
            self, "Опубликовать изменения?", self._publish_question(),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._set_busy(True)
        self._status("Публикация на сервер (может занять до минуты)…")
        worker = DeployWorker(self.bridge_root, self.ssh)
        self._threads.append(run_in_thread(worker, self._on_publish_ok, self._on_publish_error))

    def _on_publish_ok(self, output: str):
        self._set_busy(False)
        try:
            publish_summary.save_snapshot(self.bridge_root, self.snapshot_dir)
        except Exception:
            pass   # сбой снапшота не должен маскировать УСПЕШНУЮ публикацию (сводка просто будет общей)
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

    def _import_content_cards(self) -> None:
        """Точные карточки МБТ/КБТ → ручные фото профиля; внешней публикации здесь нет."""
        if self.profile.key == "carver":
            reply = QMessageBox.question(
                self, "Загрузить фото CARVER?",
                "Встроенные фото из прайса будут загружены в хранилище сайта. "
                "Позиции останутся выключенными, на Avito ничего не отправится. Продолжить?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            self._set_busy(True)
            self._status("Извлекаю и загружаю фото CARVER…")
            worker = CarverPhotoImportWorker(
                self.ssh, self.config_path, list(self.model.rows), self.local_cfg)
            self._threads.append(run_in_thread(
                worker, self._on_carver_photo_import_ok, self._on_error))
            return
        if self.profile.key != "appliances":
            return
        from avito_studio.content_card_import import import_content_cards
        try:
            found, added, removed = import_content_cards(
                self.ssh, list(self.model.rows), self.local_cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Импорт фото не удался", str(exc))
            return
        top_left = self.model.index(0, 0)
        bottom_right = self.model.index(self.model.rowCount() - 1, self.model.columnCount() - 1)
        if self.model.rowCount():
            self.model.dataChanged.emit(top_left, bottom_right)
        self._status(
            f"Карточки Контент-завода: найдено {found}, добавлено {added}, убрано дублей {removed}",
            8000)
        QMessageBox.information(
            self, "Фото импортированы",
            f"Точных уникальных совпадений: {found}.\nНовых фото добавлено: {added}.\n"
            f"Повторных карточек отключено: {removed}.\n\n"
            "Позиции с фото включены локально. На Avito ничего ещё не отправлено.")

    def _on_carver_photo_import_ok(self, found: int, added: int, preserved: int) -> None:
        self._set_busy(False)
        if self.model.rowCount():
            self.model.dataChanged.emit(
                self.model.index(0, 0),
                self.model.index(self.model.rowCount() - 1, self.model.columnCount() - 1))
        self._status(
            f"CARVER: найдено фото {found}, загружено {added}, уже было {preserved}", 8000)
        QMessageBox.information(
            self, "Фото CARVER готовы",
            f"Точно сопоставлено: {found}.\nЗагружено: {added}.\n"
            f"Сохранено ранее: {preserved}.\n\n"
            "Позиции не включены. На Avito ничего не отправлено.")

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
