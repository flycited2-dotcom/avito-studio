from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTableView,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from avito_studio import publish_summary
from avito_studio.catalog_table_model import CatalogTableModel
from avito_studio.local_config import LocalConfig
from avito_studio.profiles import PROFILES, Profile
from avito_studio.version import __version__, bridge_revision
from avito_studio.workers import (
    AppliancesPriceImportWorker,
    AvitoStatusWorker,
    CarverPhotoImportWorker,
    ContentCardImportWorker,
    DeployWorker,
    RefreshWorker,
    run_in_thread,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    refresh_done = Signal()
    refresh_stale = Signal(str)
    deploy_done = Signal()
    publish_failed = Signal(str)
    appliances_price_import_done = Signal(str, int)

    def __init__(self, bridge_root: Path, config_path: Path, ssh, snapshot_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle(f"Avito Content Studio {__version__}")
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
        self._catalog_loaded = False
        self._catalog_stale = False
        self._catalog_stale_reason = ""
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
        self.act_appliances_price = self._action(
            style.standardIcon(QStyle.SP_DialogOpenButton),
            "Импортировать XLS-прайс", self._open_appliances_price_import)
        act_refresh = self._action(style.standardIcon(QStyle.SP_BrowserReload),
                                   "Обновить каталог", self.refresh)
        self.act_publish = self._action(style.standardIcon(QStyle.SP_DialogApplyButton),
                                        "Опубликовать изменения", self.publish)
        self.act_carver_settings = self._action(
            style.standardIcon(QStyle.SP_FileDialogDetailedView),
            "Настроить публикацию", self._open_carver_publish_settings)
        act_add = self._action(style.standardIcon(QStyle.SP_FileDialogNewFolder),
                               "Добавить товар", self._open_add_forced_dialog)
        act_status = self._action(style.standardIcon(QStyle.SP_MessageBoxInformation),
                                  "Статусы Avito", self._refresh_avito_status)
        self.act_refresh = act_refresh
        self.act_add = act_add
        self.act_status = act_status
        self.act_bulk_edit = self._action(
            style.standardIcon(QStyle.SP_FileDialogListView),
            "Массовое изменение", self._open_bulk_edit_dialog)
        self.act_bulk_edit.setShortcut("Ctrl+Shift+B")
        # пока идёт фоновая операция — все действия выключены (повторный клик по «Опубликовать»
        # иначе запустил бы ВТОРОЙ параллельный деплой на боевой сервер)
        self._busy_actions = [
            act_refresh,
            self.act_publish,
            act_add,
            act_status,
            self.act_bulk_edit,
        ]
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
        self.cache_warning = self._label("", "cacheWarning")
        self.cache_warning.setWordWrap(True)
        self.cache_warning.setTextFormat(Qt.PlainText)
        self.cache_warning.setAccessibleName("Предупреждение об устаревшем кэше")
        self.cache_warning.setVisible(False)
        workspace_layout.addWidget(self.cache_warning)

        self.pages = QStackedWidget(objectName="pages")
        self.pages.addWidget(self._build_overview_page(act_refresh))
        self.pages.addWidget(self._build_catalog_page(
            act_refresh, self.act_publish, act_add, act_status))
        workspace_layout.addWidget(self.pages, 1)
        shell.addWidget(workspace, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        settings_menu = self.menuBar().addMenu("Настройки")
        settings_menu.addAction("SSH-подключение…", self._configure_connection)
        help_menu = self.menuBar().addMenu("Справка")
        help_menu.addAction("О программе…", self._show_about)
        self.statusBar().showMessage("Нажмите «Обновить», чтобы загрузить каталог с сервера")

        self._threads = []   # держим ссылки, чтобы QThread не собрался раньше времени
        self._close_when_idle = False
        self._set_busy(False)
        self._show_page(0)
        self._update_dashboard([])

    def _action(self, icon, text: str, slot):
        """Создать общее действие, пригодное для нескольких кнопок на разных страницах."""
        from PySide6.QtGui import QAction
        action = QAction(icon, text, self)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _configure_connection(self) -> None:
        """Change connection settings without touching or testing production."""
        host, accepted = QInputDialog.getText(
            self,
            "SSH-подключение",
            "Сервер (user@host):",
            text=str(getattr(self.ssh, "host", "")),
        )
        if not accepted:
            return
        current_key = str(getattr(self.ssh, "key_path", ""))
        key_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите приватный SSH-ключ",
            current_key,
            "SSH private key (*)",
        )
        if not key_path:
            return
        try:
            from avito_studio.app import save_connection_settings

            safe_host, safe_key = save_connection_settings(host, key_path)
        except Exception as exc:
            QMessageBox.warning(self, "Настройки не сохранены", str(exc))
            return
        self.ssh.host = safe_host
        self.ssh.key_path = safe_key
        self._status("SSH-подключение сохранено. Проверка выполнится при обновлении.", 6000)

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
        self.carver_settings_card = self._action_card(
            self.act_carver_settings, "Настроить CARVER", "Категория, тип товара и розничная цена")
        self.carver_settings_card.setVisible(False)
        actions.addWidget(self.carver_settings_card)
        self.appliances_price_card = self._action_card(
            self.act_appliances_price,
            "Импортировать прайс",
            "Проверка и локальное сохранение XLS без публикации",
        )
        self.appliances_price_card.setVisible(False)
        actions.addWidget(self.appliances_price_card)
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
        toolbar.addAction(self.act_appliances_price)
        toolbar.addAction(self.act_import_cards)
        toolbar.addAction(act_refresh)
        toolbar.addAction(self.act_carver_settings)
        toolbar.addAction(self.act_bulk_edit)
        toolbar.addAction(act_publish)
        toolbar.addSeparator()
        toolbar.addAction(act_add)
        toolbar.addAction(act_status)
        # Та же иерархия действий, что в карточках и диалогах.
        publish_button = toolbar.widgetForAction(act_publish)
        settings_button = toolbar.widgetForAction(self.act_carver_settings)
        price_button = toolbar.widgetForAction(self.act_appliances_price)
        add_button = toolbar.widgetForAction(act_add)
        if publish_button:
            publish_button.setProperty("role", "primary")
        if add_button:
            add_button.setProperty("role", "secondary")
        if settings_button:
            settings_button.setProperty("role", "secondary")
        if price_button:
            price_button.setProperty("role", "secondary")
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
        stale_suffix = " · КЭШ, ДАННЫЕ НЕ АКТУАЛЬНЫ" if self._catalog_stale else ""
        self.overview_catalog_text.setText(
            f"{self.profile.label}: {total} серий · выбрано {selected} · "
            f"с фото {with_cards}{stale_suffix}.")
        self.catalog_caption.setText(
            f"{total} серий · выбрано для публикации {selected}{stale_suffix} · "
            + (
                "режим только чтение"
                if self._catalog_stale
                else "двойной клик открывает карточку"
            )
        )

    def closeEvent(self, event) -> None:
        # quit() не прерывает выполняющийся worker.run(). Раньше окно ждало лишь 3 секунды,
        # затем уничтожало всё ещё работающий QThread и могло уронить процесс. Теперь закрытие
        # откладывается до штатного завершения операции.
        if self._running_threads():
            first_request = not self._close_when_idle
            self._close_when_idle = True
            event.ignore()
            self._status(
                "Окно закроется после завершения текущей операции. Не выключайте компьютер.",
                error=False,
            )
            if first_request:
                QMessageBox.information(
                    self,
                    "Операция ещё выполняется",
                    "Studio безопасно завершит текущую операцию и затем закроется автоматически.",
                )
            return
        if self.model.dirty_keys:
            try:
                self.save_local_selection()
            except Exception as exc:
                event.ignore()
                QMessageBox.critical(
                    self,
                    "Изменения не сохранены",
                    f"Окно осталось открытым: не удалось сохранить выбор товаров.\n\n{exc}",
                )
                return
        self._close_when_idle = False
        super().closeEvent(event)

    def _running_threads(self) -> list:
        running = []
        for thread in list(self._threads):
            try:
                if thread.isRunning():
                    running.append(thread)
                else:
                    self._threads.remove(thread)
            except RuntimeError:
                self._threads.remove(thread)
        return running

    def _start_worker(self, worker, on_finished, on_failed, *, on_stale=None):
        # Регистрируем поток ДО start(): быстрый worker может успеть завершиться до возврата
        # run_in_thread(), если стартовать его сразу.
        thread = run_in_thread(
            worker,
            on_finished,
            on_failed,
            on_stale=on_stale,
            on_thread_finished=self._on_worker_thread_finished,
            start=False,
        )
        self._threads.append(thread)
        thread.start()
        return thread

    @Slot()
    def _on_worker_thread_finished(self) -> None:
        finished = self.sender()
        self._threads = [thread for thread in self._threads if thread is not finished]
        if self._close_when_idle and not self._running_threads():
            QTimer.singleShot(0, self.close)

    def _set_busy(self, busy: bool) -> None:
        for act in self._busy_actions:
            act.setEnabled(not busy)
        self.profile_combo.setEnabled(not busy)   # смена профиля посреди публикации = каша путей
        # В кэш-режиме таблица доступна для поиска и прокрутки, но модель
        # снимает checkable-флаг и отвергает любые изменения.
        self.table.setEnabled(not busy)
        self.search.setEnabled(not busy)
        self.act_publish.setEnabled(
            not busy and self.profile.publish_enabled and not self._catalog_stale
        )
        can_import = self.profile.key in {"appliances", "carver"}
        self.act_import_cards.setEnabled(not busy and can_import)
        self.act_import_cards.setText(
            "Взять фото из прайса" if self.profile.key == "carver"
            else "Взять фото из Контент-завода")
        carver_active = self.profile.key == "carver"
        self.act_carver_settings.setVisible(carver_active)
        self.act_carver_settings.setEnabled(not busy and carver_active)
        appliances_active = self.profile.key == "appliances"
        self.act_appliances_price.setVisible(appliances_active)
        self.act_appliances_price.setEnabled(not busy and appliances_active)
        if hasattr(self, "appliances_price_card"):
            self.appliances_price_card.setVisible(appliances_active)
        if hasattr(self, "carver_settings_card"):
            self.carver_settings_card.setVisible(carver_active)
        if self._catalog_stale:
            for action in (self.act_add, self.act_status, self.act_bulk_edit):
                action.setEnabled(False)
            self.act_publish.setToolTip(
                "Публикация отключена: показан устаревший кэш. "
                "Сначала получите свежий каталог с сервера."
            )
        elif self.profile.publish_enabled:
            self.act_publish.setToolTip("")
        else:
            self.act_publish.setToolTip(self.profile.publish_block_reason)

    def _profile_config_path(self, profile: Profile) -> Path:
        if profile.key == PROFILES[0].key:
            return self._initial_config_path
        return self.bridge_root / profile.config_rel

    def _configured_source_file(self, config: LocalConfig | None = None) -> Path | None:
        configured = (config or self.local_cfg).get_source_path().strip()
        if not configured:
            return None
        path = Path(configured).expanduser()
        return path if path.is_absolute() else self.bridge_root / path

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
        try:
            # несохранённые галочки старого профиля — не терять
            self.save_local_selection()
        except Exception as exc:
            self.profile_combo.setCurrentIndex(
                next(i for i, p in enumerate(PROFILES) if p.key == self.profile.key)
            )
            QMessageBox.critical(
                self,
                "Профиль не переключён",
                f"Не удалось сохранить выбор текущего профиля:\n{exc}",
            )
            return
        self.profile = profile
        self.config_path = path
        self.local_cfg = new_cfg
        self._catalog_loaded = False
        self._set_cache_mode(None)
        self.profile_combo.setCurrentIndex(index)  # при программном вызове комбо ещё не переставлен
        self._install_catalog_model([])
        self._set_busy(False)
        if profile.key == "appliances":
            portable_source = "runtime/appliances/current.xls"
            runtime_price = (
                self.bridge_root / "runtime" / "appliances" / "current.xls"
            )
            configured = new_cfg.get_source_path().replace("\\", "/")
            if configured != portable_source or not runtime_price.is_file():
                self._status(
                    "Сначала нажмите «Импортировать XLS-прайс». "
                    "Отсутствующий путь со старого компьютера не открывается автоматически.",
                    10_000,
                )
                return
        if profile.key == "carver":
            source_file = self._configured_source_file(new_cfg)
            if source_file is None or not source_file.is_file():
                self._status(
                    "Сначала откройте «Настроить публикацию» и выберите свежий "
                    "XLSX-прайс CARVER. Поставщицкий файл не встроен в приложение.",
                    10_000,
                )
                return
        self.refresh()

    def _status(self, message: str, timeout: int = 0, error: bool = False) -> None:
        bar = self.statusBar()
        bar.setProperty("error", error)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.showMessage(message, timeout)

    def _set_cache_mode(self, reason: str | None) -> None:
        """Switch the visible catalog between fresh and read-only cached mode."""
        normalized = " ".join(str(reason or "").split())[:400]
        self._catalog_stale = bool(normalized)
        self._catalog_stale_reason = normalized
        if not hasattr(self, "cache_warning"):
            return
        if not self._catalog_stale:
            self.cache_warning.clear()
            self.cache_warning.setVisible(False)
            return
        self.cache_warning.setText(
            "⚠ КЭШ — ДАННЫЕ НЕ АКТУАЛЬНЫ. Серверный каталог недоступен: "
            f"{normalized}. Показан последний успешный снимок только для чтения; "
            "редактирование и публикация отключены до свежего обновления."
        )
        self.cache_warning.setVisible(True)

    def refresh(self):
        if self.profile.local_catalog:
            source_file = self._configured_source_file()
            if source_file is None or not source_file.is_file():
                action = (
                    "«Импортировать XLS-прайс»"
                    if self.profile.key == "appliances"
                    else "«Настроить публикацию»"
                )
                self._status(
                    f"Локальный прайс не найден. Сначала выберите его через {action}.",
                    10_000,
                    error=True,
                )
                return
        if self.model.dirty_keys:
            try:
                self.save_local_selection()
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Каталог не обновлён",
                    f"Сначала не удалось сохранить выбор товаров:\n{exc}",
                )
                return
        self._set_busy(True)
        self._status("Обновление локального прайса…" if self.profile.local_catalog
                     else "Обновление каталога с сервера…")
        worker = RefreshWorker(
            self.ssh,
            self.local_cfg,
            self.profile.config_rel,
            local_catalog=self.profile.local_catalog,
            profile_key=self.profile.key,
        )
        self._start_worker(
            worker,
            self._on_refresh_ok,
            self._on_error,
            on_stale=self._on_refresh_stale,
        )

    def _on_refresh_ok(self, rows):
        self._set_cache_mode(None)
        self._catalog_loaded = True
        self._install_catalog_model(rows)
        self._set_busy(False)
        published = sum(1 for r in rows if r.selected)
        self._update_dashboard(rows)
        self._status(f"Серий: {len(rows)} · публикуется: {published}")
        self.refresh_done.emit()

    def _on_refresh_stale(self, rows, reason: str):
        reason = str(reason).strip() or "сервер недоступен без описания причины"
        logger.warning(
            "Using stale catalog cache for profile %s: %s",
            self.profile.key,
            reason,
        )
        self._set_cache_mode(reason)
        # A cached snapshot is intentionally not a successful current-catalog
        # verification and must never be persisted back as the active whitelist.
        self._catalog_loaded = False
        self._install_catalog_model(rows)
        published = sum(1 for row in rows if row.selected)
        self._update_dashboard(rows)
        self._set_busy(False)
        self._status(
            f"КЭШ / НЕ АКТУАЛЬНО: {len(rows)} серий · выбрано {published}. "
            "Публикация отключена до свежего обновления.",
            error=True,
        )
        self.refresh_stale.emit(self._catalog_stale_reason)
        self.refresh_done.emit()

    def _install_catalog_model(self, rows) -> None:
        per_item = self.profile.key != "conditioners"
        self.model = CatalogTableModel(
            rows,
            per_item=per_item,
            read_only=self._catalog_stale,
        )
        self.proxy.setSourceModel(self.model)
        self.table.setColumnHidden(CatalogTableModel.COL_SIZES, per_item)

    def save_local_selection(self):
        # Сохраняем ПОЛНЫЙ видимый whitelist. Поштучный set_selected не способен
        # корректно выразить «все, кроме одного», когда исходное [] означает «все».
        # До первого успешного refresh модель пуста, но это НЕ означает, что владелец
        # выбрал «ничего»: нельзя затереть существующий whitelist простым запуском Studio.
        if self._catalog_loaded:
            self.local_cfg.replace_selected(
                row.key for row in self.model.rows if row.selected
            )
        self.local_cfg.save()
        self.model.dirty_keys.clear()

    def _publish_question(self) -> str:
        """Текст подтверждения: конкретная сводка изменений с прошлой публикации, если есть база."""
        changes = publish_summary.summarize_changes(
            self.bridge_root,
            self.snapshot_dir,
            config_path=self.config_path,
            profile_key=self.profile.key,
        )
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
        if self._catalog_stale:
            QMessageBox.warning(
                self,
                "Публикация заблокирована",
                "Сейчас показан устаревший кэш каталога. Он доступен только для "
                "просмотра и не считается свежей проверкой. Восстановите соединение "
                "с сервером и нажмите «Обновить каталог».",
            )
            return
        if not self.profile.publish_enabled:
            QMessageBox.warning(self, "Публикация недоступна",
                                self.profile.publish_block_reason)
            return
        # галочки «Публикуется» сохраняем локально ДО сводки — иначе их не будет в списке;
        # локальная запись безвредна (диалоги и так пишут локально, публикация — отдельный шаг)
        self.save_local_selection()
        if self.profile.key == "carver":
            from avito_studio.carver_readiness import carver_publish_issues
            issues = carver_publish_issues(self.config_path, self.model.rows)
            if issues:
                QMessageBox.warning(
                    self, "CARVER ещё не готов к публикации",
                    "Перед отправкой генераторов на Avito нужно закрыть пункты:\n\n"
                    + "\n".join(f"• {issue}" for issue in issues))
                return
        reply = QMessageBox.question(
            self, "Опубликовать изменения?", self._publish_question(),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._set_busy(True)
        self._status("Публикация на сервер (может занять до минуты)…")
        worker = DeployWorker(
            self.bridge_root, self.ssh, config_path=self.config_path,
            local_feed=self.profile.local_catalog)
        self._start_worker(worker, self._on_publish_ok, self._on_publish_error)

    def _on_publish_ok(self, output: str):
        self._set_busy(False)
        try:
            publish_summary.save_snapshot(
                self.bridge_root,
                self.snapshot_dir,
                config_path=self.config_path,
                profile_key=self.profile.key,
            )
        except Exception as exc:
            # Publication has already committed remotely, so snapshot failure
            # cannot turn it into a false deployment failure.  It must still be
            # visible in diagnostics for recovery and support.
            logger.warning(
                "Published profile %s, but could not save local snapshot: %s",
                self.profile.key,
                exc,
            )
        summary = " ".join(str(output).split())
        self._status(
            "Опубликовано и проверено."
            + (f" {summary[:220]}" if summary else ""),
            10_000,
        )
        self.deploy_done.emit()

    def _on_publish_error(self, message: str):
        logger.error("Publication failed for profile %s: %s", self.profile.key, message)
        self._set_busy(False)
        self._status(f"Ошибка публикации: {message}", error=True)
        # модально: провал публикации нельзя показывать только строкой статуса —
        # пользователь решит, что изменения ушли на Avito, а они не ушли
        QMessageBox.critical(self, "Публикация не удалась",
                             f"Изменения НЕ попали на сервер.\n\nПричина: {message}")
        self.publish_failed.emit(message)

    def _on_error(self, message: str):
        logger.error("Background operation failed for profile %s: %s", self.profile.key, message)
        self._set_busy(False)
        self._status(f"Ошибка: {message}", error=True)

    def _open_edit_dialog(self, proxy_index) -> None:
        if self._catalog_stale:
            QMessageBox.information(
                self,
                "Каталог открыт только для чтения",
                "Показан устаревший кэш. Для редактирования сначала восстановите "
                "соединение и получите свежий каталог.",
            )
            return
        from avito_studio.edit_dialog import EditSeriesDialog
        source_index = self.proxy.mapToSource(proxy_index)
        row = self.model.rows[source_index.row()]
        dlg = EditSeriesDialog(
            row,
            self.bridge_root,
            self.local_cfg,
            self.ssh,
            profile=self.profile,
            parent=self,
        )
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

    def _open_bulk_edit_dialog(self) -> None:
        from avito_studio.bulk_edit_dialog import BulkEditDialog

        dialog = BulkEditDialog(self.model.rows, self.local_cfg, parent=self)
        dialog.applied.connect(self._on_bulk_applied)
        dialog.exec()

    def _on_bulk_applied(self, preview) -> None:
        selection_updates = {
            change.key: change.new_selected for change in preview.series_changes}
        price_updates = {
            change.nc_code: change.new_price
            for change in preview.price_changes
            if change.new_price is not None
        }
        for row in self.model.rows:
            if row.key in selection_updates:
                row.selected = selection_updates[row.key]
            if price_updates:
                row.members = tuple(
                    replace(member, current_price=price_updates[member.nc_code])
                    if member.nc_code in price_updates else member
                    for member in row.members
                )
                prices = sorted(
                    member.current_price for member in row.members
                    if member.price_ok and member.current_price is not None
                )
                if prices:
                    row.price_range = (
                        f"{prices[0]} ₽" if len(set(prices)) == 1
                        else f"{prices[0]}–{prices[-1]} ₽")
        if self.model.rows:
            top_left = self.model.index(0, 0)
            bottom_right = self.model.index(
                self.model.rowCount() - 1, self.model.columnCount() - 1)
            self.model.dataChanged.emit(top_left, bottom_right)
        self._update_dashboard(self.model.rows)
        self._status(
            f"Сохранено локально: публикация {len(preview.series_changes)}, "
            f"цены {len(preview.price_changes)}. Для отправки нажмите «Опубликовать изменения».",
            8000,
        )

    def _open_add_forced_dialog(self) -> None:
        from avito_studio.add_forced_dialog import AddForcedProductDialog
        dlg = AddForcedProductDialog(
            self.local_cfg, self.ssh, profile=self.profile, parent=self)
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

    def _open_carver_publish_settings(self) -> None:
        """Open the one-time profile setup without publishing anything externally."""
        if self.profile.key != "carver":
            return
        from avito_studio.carver_publish_settings_dialog import (
            CarverPublishSettingsDialog,
        )

        dlg = CarverPublishSettingsDialog(self.local_cfg, parent=self)
        if not dlg.exec():
            return
        try:
            dlg.save()
        except Exception as exc:
            QMessageBox.critical(self, "Настройки не сохранены", str(exc))
            return
        self._status("Настройки CARVER сохранены. Теперь обновите каталог и выберите позиции.", 7000)
        QMessageBox.information(
            self,
            "Настройка CARVER сохранена",
            "Категория и расчёт цены сохранены для профиля CARVER.\n\n"
            "Дальше: обновите каталог, отметьте позиции, загрузите фото из прайса и публикуйте фид.",
        )

    def _show_about(self) -> None:
        from avito_studio.diagnostics import default_log_dir

        revision = bridge_revision()
        short_revision = revision[:12] if revision != "development" else revision
        QMessageBox.about(
            self,
            "О программе",
            f"Avito Content Studio {__version__}\n"
            f"Совместимый Avito Bridge: {short_revision}\n\n"
            f"Диагностический журнал:\n{default_log_dir() / 'studio.log'}",
        )

    def _open_appliances_price_import(self) -> None:
        """Choose and install a local supplier XLS without any external action."""
        if self.profile.key != "appliances":
            return
        from avito_studio.ui_components import get_open_file_name

        runtime_dir = self.bridge_root / "runtime" / "appliances"
        initial_dir = str(runtime_dir) if runtime_dir.is_dir() else ""
        source, _ = get_open_file_name(
            self,
            "Выберите XLS-прайс бытовой техники",
            initial_dir,
            "Прайс Excel 97–2003 (*.xls)",
        )
        if not source:
            return
        self._set_busy(True)
        self._status("Проверяю и безопасно импортирую XLS-прайс…")
        worker = AppliancesPriceImportWorker(
            Path(source), self.bridge_root, self.local_cfg
        )
        self._start_worker(
            worker,
            self._on_appliances_price_import_ok,
            self._on_appliances_price_import_error,
        )

    def _on_appliances_price_import_ok(self, target: str, count: int) -> None:
        self._set_busy(False)
        self._catalog_loaded = False
        self._status(
            f"XLS-прайс сохранён локально: {count} позиций. "
            "Нажмите «Обновить каталог».",
            9000,
        )
        self.appliances_price_import_done.emit(target, count)
        QMessageBox.information(
            self,
            "Прайс импортирован",
            f"Проверено и сохранено позиций: {count}.\n"
            "Профиль переведён на переносимый локальный файл.\n\n"
            "На сервер и Avito ничего не отправлено. "
            "Нажмите «Обновить каталог», чтобы увидеть новый прайс.",
        )

    def _on_appliances_price_import_error(self, message: str) -> None:
        self._on_error(message)
        QMessageBox.critical(
            self,
            "Прайс не импортирован",
            f"{message}\n\nСтарый локальный прайс и настройки сохранены.",
        )

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
            self._start_worker(worker, self._on_carver_photo_import_ok, self._on_error)
            return
        if self.profile.key != "appliances":
            return
        self._set_busy(True)
        self._status("Ищу и импортирую карточки Контент-завода…")
        worker = ContentCardImportWorker(
            self.ssh, list(self.model.rows), self.local_cfg
        )
        self._start_worker(
            worker, self._on_content_card_import_ok, self._on_content_card_import_error
        )

    def _on_content_card_import_ok(
        self, found: int, added: int, removed: int
    ) -> None:
        self._set_busy(False)
        if self.model.rowCount():
            top_left = self.model.index(0, 0)
            bottom_right = self.model.index(
                self.model.rowCount() - 1, self.model.columnCount() - 1
            )
            self.model.dataChanged.emit(top_left, bottom_right)
        self._status(
            f"Карточки Контент-завода: найдено {found}, добавлено {added}, убрано дублей {removed}",
            8000)
        QMessageBox.information(
            self, "Фото импортированы",
            f"Точных уникальных совпадений: {found}.\nНовых фото добавлено: {added}.\n"
            f"Повторных карточек отключено: {removed}.\n\n"
            "Позиции с фото включены локально. На Avito ничего ещё не отправлено.")

    def _on_content_card_import_error(self, message: str) -> None:
        self._on_error(message)
        QMessageBox.critical(self, "Импорт фото не удался", message)

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
        worker = AvitoStatusWorker(
            self.bridge_root, list(self.model.rows), self.profile.key
        )
        self._start_worker(worker, self._on_avito_status_ok, self._on_error)

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
