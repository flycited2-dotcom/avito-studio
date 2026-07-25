"""Точечная генерация карточки для ОДНОЙ серии — SSH-вызов cards_run с ключом серии.
Асинхронно: ставит задачу в очередь фотоагента (WatchDog+веб-ChatGPT на ПК владельца её заберут),
готовая карточка появится не сразу — следующее «Обновить» в таблице покажет has_card=True."""
from __future__ import annotations

import shlex

REMOTE_CARDS_RUN_CMD = ("cd /opt/avito-bridge && export PYTHONPATH=src && "
                        ".venv/bin/python -m avito_bridge.cards_run {key}")


def generate_card(ssh, series_key: str) -> str:
    """ssh — объект с .run(cmd) -> str (см. SshClient)."""
    return ssh.run(REMOTE_CARDS_RUN_CMD.format(key=shlex.quote(series_key)))
