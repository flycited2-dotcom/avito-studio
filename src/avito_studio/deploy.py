"""Публикация изменений: пакует config/ + avito-descriptions/ из локального checkout avito-bridge,
заливает на VPS, запускает генерацию карточек и пересборку фида. Тот же финальный шаг, что и в
avito-bridge/scripts/apply_inbox.py, но не трогаем сам этот боевой скрипт — своя маленькая копия."""
from __future__ import annotations
import posixpath
import shlex
import tarfile
import tempfile
from pathlib import Path
from avito_bridge.config import load_config
from avito_bridge.ingest.sources import get_source
from avito_bridge.orchestrator.pipeline import run_cycle

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
            # YAML профилей (венки и далее) правится студией так же, как config.yaml —
            # обязан уезжать тем же деплоем; папки может не быть в старых checkout'ах
            if (bridge_root / "profiles").is_dir():
                tar.add(bridge_root / "profiles", arcname="profiles")
        ssh.put("/tmp/studio_deploy.tgz", tgz.read_bytes())
    return ssh.run(REMOTE_DEPLOY_CMD)


def _remote_feed_path(feed_path: str) -> str:
    clean = str(feed_path or "").replace("\\", "/").strip("/")
    normalized = posixpath.normpath(clean)
    if not normalized or normalized == "." or normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"Небезопасный путь фида: {feed_path!r}")
    return "/opt/avito-bridge/" + normalized


def deploy_local_feed(config_path: Path, ssh) -> str:
    """Build a local price-based profile on Windows and upload the ready XML feed."""
    cfg = load_config(Path(config_path))
    with tempfile.TemporaryDirectory() as tmp:
        feed_path = Path(tmp) / Path(cfg.feed_path).name
        state_path = Path(tmp) / "state.db"
        offers = get_source(cfg.source)(cfg)
        result = run_cycle(lambda: offers, cfg, feed_path=feed_path, state_path=state_path)
        remote_path = _remote_feed_path(cfg.feed_path)
        ssh.run(f"mkdir -p {shlex.quote(posixpath.dirname(remote_path))}")
        ssh.put(remote_path, feed_path.read_bytes())
    label = cfg.profile_name or Path(config_path).stem
    return (f"profile={label} feed_uploaded={remote_path} "
            f"offers_in={result.offers_in} ads_built={result.ads_built} skipped={result.skipped}")
