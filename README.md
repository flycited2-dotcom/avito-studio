# Avito Content Studio

Windows GUI поверх движка `avito-bridge`: обзор каталога, включение/выключение публикации серий,
деплой на боевой Avito Bridge (VPS 213.109.202.45).

## Установка (dev)
    python -m venv .venv
    .venv/Scripts/pip install -e ../avito-bridge
    .venv/Scripts/pip install -e .[dev]

## Запуск
    python -m avito_studio

## Тесты
    pytest
