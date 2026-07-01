"""Публикация изменений: пакует config/ + avito-descriptions/ из локального checkout avito-bridge,
заливает на VPS, запускает генерацию карточек и пересборку фида. Тот же финальный шаг, что и в
avito-bridge/scripts/apply_inbox.py, но не трогаем сам этот боевой скрипт — своя маленькая копия."""
from __future__ import annotations
import tarfile
import tempfile
from pathlib import Path

REMOTE_DEPLOY_CMD = ("cd /opt/avito-bridge && tar -xzf /tmp/studio_deploy.tgz && "
                     "export PYTHONPATH=src && .venv/bin/python -m avito_bridge.cards_run && "
                     "systemctl start avito-bridge.service")


def deploy_and_rebuild(bridge_root: Path, ssh) -> str:
    """bridge_root — путь к локальному checkout avito-bridge. ssh — объект с .put()/.run() (SshClient)."""
    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / "studio_deploy.tgz"
        with tarfile.open(tgz, "w:gz") as tar:
            tar.add(bridge_root / "config", arcname="config")
            tar.add(bridge_root / "avito-descriptions", arcname="avito-descriptions")
        ssh.put("/tmp/studio_deploy.tgz", tgz.read_bytes())
    return ssh.run(REMOTE_DEPLOY_CMD)
