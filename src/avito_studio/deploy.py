"""Публикация изменений: пакует config/ + avito-descriptions/ из локального checkout avito-bridge,
заливает на VPS, запускает генерацию карточек и пересборку фида. Тот же финальный шаг, что и в
avito-bridge/scripts/apply_inbox.py, но не трогаем сам этот боевой скрипт — своя маленькая копия."""
from __future__ import annotations
import posixpath
import shlex
import tarfile
import tempfile
import xml.etree.ElementTree as ET
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


def _public_feed_path(public_feed_path: str) -> str:
    normalized = posixpath.normpath(str(public_feed_path or "").replace("\\", "/"))
    public_root = "/opt/oasis/staticfiles"
    if not normalized.startswith(public_root + "/"):
        raise ValueError(
            "Небезопасный путь публичного фида: ожидается файл внутри "
            f"{public_root}/, получено {public_feed_path!r}"
        )
    return normalized


def validate_feed_xml(data: bytes, expected_ads: int) -> None:
    """Reject a malformed or incomplete feed before any public file is replaced."""
    if expected_ads < 1:
        raise ValueError("Публичный фид должен содержать хотя бы одно объявление.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"Некорректный XML-фид: {exc}") from exc
    if root.tag != "Ads":
        raise ValueError(f"Корневой элемент XML должен быть Ads, получено {root.tag!r}.")
    ads = root.findall("Ad")
    if len(ads) != expected_ads:
        raise ValueError(
            f"Ожидалось объявлений: {expected_ads}, найдено в XML: {len(ads)}."
        )
    required = ("Id", "Title", "Description", "Price")
    for index, ad in enumerate(ads, start=1):
        for tag in required:
            if not str(ad.findtext(tag, "")).strip():
                raise ValueError(f"В объявлении {index} отсутствует обязательное поле {tag}.")
        image = ad.find("Images/Image")
        image_url = "" if image is None else str(image.get("url", "") or image.text or "")
        if not image_url.strip():
            raise ValueError(f"В объявлении {index} отсутствует обязательное поле Images/Image.")


def deploy_local_feed(config_path: Path, ssh) -> str:
    """Build a local price-based profile on Windows and upload the ready XML feed."""
    cfg = load_config(Path(config_path))
    public_path = _public_feed_path(cfg.public_feed_path)
    public_dir = posixpath.dirname(public_path)
    temporary_path = posixpath.join(public_dir, f".{posixpath.basename(public_path)}.tmp")
    with tempfile.TemporaryDirectory() as tmp:
        feed_path = Path(tmp) / Path(cfg.feed_path).name
        state_path = Path(tmp) / "state.db"
        offers = get_source(cfg.source)(cfg)
        result = run_cycle(lambda: offers, cfg, feed_path=feed_path, state_path=state_path)
        data = feed_path.read_bytes()
        validate_feed_xml(data, expected_ads=result.ads_built)
        ssh.run(f"mkdir -p {shlex.quote(public_dir)}")
        ssh.put(temporary_path, data)
        validation_script = (
            "import sys; import xml.etree.ElementTree as ET; "
            "root = ET.parse(sys.argv[1]).getroot(); "
            "assert root.tag == 'Ads'; "
            "assert len(root.findall('Ad')) == int(sys.argv[2])"
        )
        command = (
            f"python3 -c {shlex.quote(validation_script)} "
            f"{shlex.quote(temporary_path)} {result.ads_built} && "
            f"mv -f {shlex.quote(temporary_path)} {shlex.quote(public_path)}"
        )
        ssh.run(command)
    label = cfg.profile_name or Path(config_path).stem
    return (f"profile={label} feed_uploaded={public_path} "
            f"offers_in={result.offers_in} ads_built={result.ads_built} skipped={result.skipped}")
