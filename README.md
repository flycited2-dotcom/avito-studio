# Avito Content Studio

Avito Content Studio — Windows-приложение для управления профилями
`avito-bridge`: просмотра и фильтрации каталога, ручного и массового
редактирования товаров, описаний и цен, импорта контент-карточек, проверки
статусов Avito и контролируемой публикации.

Текущая линия совместимости Studio и Bridge — `0.3.x`.

## Профили и границы публикации

- **Кондиционеры** — основной серверный профиль; доступны карточки контента,
  ручные изменения и безопасная публикация через серверный кандидат.
- **Венки** — отдельный профиль и публичный фид; публикуется тем же безопасным
  серверным маршрутом.
- **Генераторы CARVER** — каталог собирается локально из выбранного XLSX; XML
  проверяется до загрузки и атомарно заменяет только профильный фид.
- **Бытовая техника** — режим предпросмотра. Кнопка публикации отключена, пока
  не подтверждены категории, наценки, фото и объединение с основным фидом.

Редактирование и публикация — разные действия. Изменения сначала сохраняются
локально и показываются в сводке; отправка начинается только по отдельной
команде пользователя.

## Первый запуск и автономная работа

Запуск приложения не обращается к SSH и Avito автоматически. Обновление
каталога и статусов начинается только после явного нажатия «Обновить».

Windows-сборка содержит шаблон `config/`, `profiles/` и
`avito-descriptions/`. Поставочные XLS/XLSX в EXE не входят: CARVER и бытовая
техника импортируются пользователем в отдельное локальное runtime-хранилище.
При первом запуске шаблон устанавливается в:

```text
%LOCALAPPDATA%\AvitoStudio\bridge
```

Новые версии Studio выполняют аддитивное обновление шаблона: добавляют новые
файлы и отсутствующие YAML-ключи, не перезаписывая пользовательские значения,
списки и комментарии. Обновление готовится целиком и меняет workspace только
после проверки; предыдущая версия сохраняется до успешной замены. Если Studio
запущена из исходников или нужен другой checkout, в первом окне выберите
папку `avito-bridge`, внутри которой существует `config/config.yaml`.

Диагностический журнал всегда записывается в:

```text
%LOCALAPPDATA%\AvitoStudio\logs\studio.log
```

Файл ротируется: до 2 MiB, пять резервных копий. Необработанная ошибка
показывается в интерфейсе и записывается туда же.

## Локальный Bridge и SSH

Параметры сохраняются отдельно для текущего пользователя. SSH настраивается
через **Настройки → SSH-подключение…** и проверяется только при сетевой
операции. Нужны установленный Windows OpenSSH Client и существующий приватный
ключ. Свежая установка не содержит production-хост, пароль, токен или
приватный ключ: до настройки серверные операции завершаются безопасной
ошибкой.

Для управляемого запуска настройки можно переопределить переменными среды:

| Переменная | Назначение |
| --- | --- |
| `AVITO_STUDIO_BRIDGE_ROOT` | проверенный локальный корень `avito-bridge` |
| `AVITO_STUDIO_SSH_HOST` | сервер в виде `user@host` или `host` |
| `AVITO_STUDIO_SSH_KEY` | путь к приватному SSH-ключу |

Явно заданный, но неверный `AVITO_STUDIO_BRIDGE_ROOT` не подменяется другим
checkout: Studio открывает безопасное окно настройки.

Совместимый commit Bridge записан в `bridge.lock`. Файл содержит ровно один
40-символьный lowercase Git hash. Для сборки требуется точное совпадение `HEAD`
и чистый рабочий каталог Bridge:

```powershell
$required = (Get-Content bridge.lock -Raw).Trim()
$actual = (git -C ../avito-bridge rev-parse HEAD).Trim()
if ($actual -ne $required) { throw "Bridge revision mismatch" }
if (git -C ../avito-bridge status --porcelain) { throw "Bridge checkout is dirty" }
```

## Установка для разработки

Репозитории должны лежать рядом:

```text
Avito/
├── avito-bridge/
└── avito-studio/
```

В PowerShell из `avito-studio`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "..\avito-bridge[dev]"
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Запуск:

```powershell
.\.venv\Scripts\python.exe -m avito_studio
```

Полная локальная проверка Studio:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m ruff check src tests --select E9,F
.\.venv\Scripts\python.exe -m coverage run -m pytest -q --disable-socket
.\.venv\Scripts\python.exe -m coverage report --fail-under=86
```

CI отдельно запускает тесты Bridge, затем тесты Studio с отключённой сетью и
branch coverage только пакета `avito_studio`.

## Windows-сборка и smoke-test

Spec включает код и профильные шаблоны из соседнего checkout Bridge, поэтому
его `HEAD` должен точно соответствовать `bridge.lock`, а checkout должен быть
чистым. Это не позволяет пометить EXE старым SHA при фактически изменённом
коде или шаблонах.

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean avito_studio.spec
.\dist\AvitoContentStudio.exe --smoke-test
```

Результат — `dist/AvitoContentStudio.exe`. Режим `--smoke-test` запускает
настоящее упакованное приложение, создаёт локальный шаблон и журнал, не
подключается к production и внутри реального цикла Qt проверяет главное окно,
четыре профиля, навигацию, поиск и блокировку небезопасной публикации
`appliances`. Ошибка любой проверки даёт ненулевой exit code. Smoke-запуск не
сохраняет временный `bridge_root` в Windows QSettings. CI запускает его с
изолированным `LOCALAPPDATA` и проверяет наличие встроенных `config/`, всех
профильных YAML и непустого журнала.

Технический отчёт текущего ревью:
[`docs/QUALITY_REVIEW_2026-07-25.md`](docs/QUALITY_REVIEW_2026-07-25.md).
