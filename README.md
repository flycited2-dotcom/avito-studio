# Avito Content Studio

Windows GUI поверх движка `avito-bridge`: обзор каталога, включение/выключение публикации серий,
деплой на боевой Avito Bridge (VPS 213.109.202.45).

## Установка (dev)

    python -m venv .venv
    .venv/Scripts/pip install -e ../avito-bridge
    .venv/Scripts/pip install -e .[dev]

Проверенная ревизия Bridge записана в `bridge.lock`. Перед разработкой убедитесь, что локальный
`../avito-bridge` содержит этот коммит:

    git -C ../avito-bridge merge-base --is-ancestor (Get-Content bridge.lock).Trim() HEAD

## Запуск

    python -m avito_studio

## Тесты

    python -m pytest -q

## Windows-сборка

    python -m PyInstaller --noconfirm --clean avito_studio.spec

Результат появляется в `dist/AvitoContentStudio.exe`. Каталоги `build/`, `dist/`,
`build-candidate/` и `dist-candidate/` не коммитятся.
