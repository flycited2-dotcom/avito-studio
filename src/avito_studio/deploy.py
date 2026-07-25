"""Публикация изменений: пакует config/ + avito-descriptions/ из локального checkout avito-bridge,
заливает на VPS, запускает генерацию карточек и пересборку фида. Тот же финальный шаг, что и в
avito-bridge/scripts/apply_inbox.py, но не трогаем сам этот боевой скрипт — своя маленькая копия."""
from __future__ import annotations
import io
import json
import posixpath
import re
import shlex
import tarfile
import tempfile
import uuid
from pathlib import Path

from defusedxml import ElementTree as ET
from avito_bridge.config import load_config
from avito_bridge.ingest.sources import fetch_profile_offers
from avito_bridge.orchestrator.pipeline import run_cycle
from avito_studio import description_store

_PROFILE_CONFIG = re.compile(
    r"(?:config/config\.yaml|profiles/[A-Za-z0-9_.-]+\.yaml)\Z"
)
_REMOTE_PROFILE_KEYS = {
    "config/config.yaml": "conditioners",
    "profiles/wreaths.yaml": "wreaths",
    "profiles/carver.yaml": "carver",
}
_LOCAL_PUBLISH_TARGETS = {
    ("config", "config.yaml"): ("conditioners", "avito-feed.xml"),
    ("profiles", "wreaths.yaml"): ("wreaths", "avito-feed-wreaths.xml"),
    ("profiles", "carver.yaml"): ("carver", "avito-feed-carver.xml"),
}
_LOCAL_BACKUP_RECOVERY_SCRIPT = r"""
import json, os, shutil, sys, uuid
from pathlib import Path

root, prefix, public = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])

def atomic_json(path, value):
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

if root.is_dir():
    for directory in sorted(root.iterdir()):
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or not directory.name.startswith(prefix)
        ):
            continue
        journal_path = directory / "transaction.json"
        if not journal_path.is_file():
            continue
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("status") in {"committed", "rolled_back"}:
            continue
        if journal.get("schema_version") != 1 or journal.get("status") != "prepared":
            raise RuntimeError("invalid local publication journal: " + str(journal_path))
        if Path(journal.get("public_feed", "")).resolve() != public.resolve():
            raise RuntimeError("local publication journal target mismatch")
        backup = directory / public.name
        if journal.get("had_previous"):
            if not backup.is_file():
                raise RuntimeError("local publication backup is missing: " + str(backup))
            public.parent.mkdir(parents=True, exist_ok=True)
            temporary = public.with_name("." + public.name + ".recovery-" + uuid.uuid4().hex)
            shutil.copyfile(backup, temporary)
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, public)
        else:
            public.unlink(missing_ok=True)
        if os.name != "nt":
            descriptor = os.open(public.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        journal["status"] = "rolled_back"
        atomic_json(journal_path, journal)
"""
_LOCAL_BACKUP_PREPARE_SCRIPT = r"""
import json, os, shutil, sys, uuid
from pathlib import Path

directory, public = Path(sys.argv[1]), Path(sys.argv[2])
directory.mkdir(parents=True, exist_ok=False)
backup = directory / public.name
had_previous = public.is_file()
if had_previous:
    shutil.copyfile(public, backup)
    with backup.open("r+b") as stream:
        os.fsync(stream.fileno())
journal = {
    "schema_version": 1,
    "status": "prepared",
    "public_feed": str(public.resolve()),
    "had_previous": had_previous,
}
path = directory / "transaction.json"
temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
with temporary.open("w", encoding="utf-8") as stream:
    json.dump(journal, stream, ensure_ascii=False, sort_keys=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
if os.name != "nt":
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
"""
_LOCAL_BACKUP_COMMIT_SCRIPT = r"""
import json, os, sys, uuid
from pathlib import Path

directory, public = Path(sys.argv[1]), Path(sys.argv[2])
path = directory / "transaction.json"
journal = json.loads(path.read_text(encoding="utf-8"))
if journal.get("schema_version") != 1 or journal.get("status") != "prepared":
    raise RuntimeError("local publication journal is not prepared")
if Path(journal.get("public_feed", "")).resolve() != public.resolve():
    raise RuntimeError("local publication journal target mismatch")
with public.open("r+b") as stream:
    os.fsync(stream.fileno())
if os.name != "nt":
    descriptor = os.open(public.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
journal["status"] = "committed"
temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
with temporary.open("w", encoding="utf-8") as stream:
    json.dump(journal, stream, ensure_ascii=False, sort_keys=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
if os.name != "nt":
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
"""
_LOCAL_BACKUP_RETENTION_SCRIPT = r"""
import json, shutil, sys
from pathlib import Path

root, prefix, keep = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
completed = []
if root.is_dir():
    for directory in root.iterdir():
        journal = directory / "transaction.json"
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or not directory.name.startswith(prefix)
            or not journal.is_file()
        ):
            continue
        try:
            status = json.loads(journal.read_text(encoding="utf-8")).get("status")
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if status in {"committed", "rolled_back"}:
            completed.append((journal.stat().st_mtime_ns, directory.name, directory))
completed.sort(reverse=True)
for _mtime, _name, directory in completed[keep:]:
    shutil.rmtree(directory)
"""


def _config_relative(bridge_root: Path, config_path: Path | None) -> str:
    bridge_root = Path(bridge_root).resolve()
    selected = (
        bridge_root / "config" / "config.yaml"
        if config_path is None
        else Path(config_path).resolve()
    )
    try:
        relative = selected.relative_to(bridge_root).as_posix()
    except ValueError as exc:
        raise ValueError("Конфиг профиля должен находиться внутри avito-bridge.") from exc
    if not _PROFILE_CONFIG.fullmatch(relative):
        raise ValueError(
            "Поддерживается config/config.yaml либо YAML непосредственно в profiles/."
        )
    if not selected.is_file():
        raise FileNotFoundError(f"Конфиг профиля не найден: {selected}")
    return relative


def deploy_and_rebuild(
    bridge_root: Path,
    ssh,
    config_path: Path | None = None,
) -> str:
    """Safely publish one remote-source profile through a validated candidate."""
    bridge_root = Path(bridge_root)
    config_rel = _config_relative(bridge_root, config_path)
    profile_key = _REMOTE_PROFILE_KEYS.get(config_rel)
    if profile_key is None:
        raise ValueError(
            f"Конфиг {config_rel!r} не привязан к разрешённому профилю публикации."
        )
    description_patch = description_store.build_profile_patch(
        bridge_root, profile_key
    )
    remote_upload_dir = "/opt/avito-bridge/runtime/studio-uploads"
    remote_archive = (
        f"{remote_upload_dir}/avito-studio-{uuid.uuid4().hex}.tgz"
    )
    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / "studio_deploy.tgz"
        with tarfile.open(tgz, "w:gz") as tar:
            tar.add(bridge_root / Path(config_rel), arcname=config_rel)
            patch_data = (
                json.dumps(
                    description_patch,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
            patch_info = tarfile.TarInfo("description-patch/patch.json")
            patch_info.size = len(patch_data)
            patch_info.mode = 0o600
            tar.addfile(patch_info, io.BytesIO(patch_data))
            for filename in sorted(set(description_patch["upserts"].values())):
                data = (bridge_root / "avito-descriptions" / filename).read_bytes()
                info = tarfile.TarInfo(f"description-patch/files/{filename}")
                info.size = len(data)
                info.mode = 0o600
                tar.addfile(info, io.BytesIO(data))
        ssh.run(f"install -d -m 700 {shlex.quote(remote_upload_dir)}")
        ssh.put(remote_archive, tgz.read_bytes())

    archive_q = shlex.quote(remote_archive)
    config_q = shlex.quote(config_rel)
    cleanup = shlex.quote(f"rm -f -- {remote_archive}")
    command = (
        "cd /opt/avito-bridge && "
        f"trap {cleanup} EXIT && "
        "export PYTHONPATH=src && "
        ".venv/bin/python -m avito_bridge.profile_publish "
        f"--archive {archive_q} --config {config_q}"
    )
    result = ssh.run(command)
    # Clear only the exact generation sent.  Concurrent edits intentionally
    # remain pending; repeating an already applied patch is idempotent.
    description_store.acknowledge_profile_patch(
        bridge_root, profile_key, description_patch
    )
    return result


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
            "Профиль можно публиковать только в безопасный файл внутри "
            f"{public_root}/, получено {public_feed_path!r}"
        )
    return normalized


def _validated_local_publish_target(config_path: Path, cfg) -> str:
    """Bind a local profile file to its one permitted public account feed."""
    resolved = Path(config_path).resolve()
    identity = (resolved.parent.name, resolved.name)
    expected = _LOCAL_PUBLISH_TARGETS.get(identity)
    if expected is None:
        raise ValueError(
            "Этот конфиг не разрешён для публикации; используйте штатный файл "
            "из config/ или profiles/."
        )
    expected_profile, expected_filename = expected
    if cfg.profile_name != expected_profile:
        raise ValueError(
            f"{resolved.name} должен содержать profile.name={expected_profile!r}, "
            f"получено {cfg.profile_name!r}."
        )
    actual = _public_feed_path(cfg.public_feed_path)
    required = f"/opt/oasis/staticfiles/{expected_filename}"
    if actual != required:
        raise ValueError(
            f"Профиль {expected_profile!r} можно публиковать только в "
            f"{required}, получено {actual}."
        )
    return actual


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
    seen: set[str] = set()
    for index, ad in enumerate(ads, start=1):
        for tag in required:
            if not str(ad.findtext(tag, "")).strip():
                raise ValueError(f"В объявлении {index} отсутствует обязательное поле {tag}.")
        ad_id = str(ad.findtext("Id", "")).strip()
        if ad_id in seen:
            raise ValueError(f"В XML повторяется Id объявления: {ad_id}.")
        seen.add(ad_id)
        image = ad.find("Images/Image")
        image_url = "" if image is None else str(image.get("url", "") or image.text or "")
        if not image_url.strip():
            raise ValueError(f"В объявлении {index} отсутствует обязательное поле Images/Image.")


def deploy_local_feed(config_path: Path, ssh) -> str:
    """Build a local price-based profile on Windows and upload the ready XML feed."""
    cfg = load_config(Path(config_path))
    public_path = _validated_local_publish_target(Path(config_path), cfg)
    if cfg.profile_name == "carver":
        from avito_studio.carver_price_file import (
            resolve_carver_price_path,
            validate_carver_price_metadata,
        )

        configured_source = (cfg.source_options or {}).get("path", "")
        if not configured_source:
            raise ValueError("В профиле CARVER не указан XLSX-прайс.")
        validate_carver_price_metadata(
            resolve_carver_price_path(Path(config_path), configured_source)
        )
    public_dir = posixpath.dirname(public_path)
    temporary_path = posixpath.join(
        public_dir,
        f".{posixpath.basename(public_path)}.{uuid.uuid4().hex}.tmp",
    )
    with tempfile.TemporaryDirectory() as tmp:
        feed_path = Path(tmp) / Path(cfg.feed_path).name
        state_path = Path(tmp) / "state.db"
        offers = fetch_profile_offers(cfg)
        result = run_cycle(lambda: offers, cfg, feed_path=feed_path, state_path=state_path)
        data = feed_path.read_bytes()
        validate_feed_xml(data, expected_ads=result.ads_built)
        lock_path = "/opt/avito-bridge/state/profile-publish.lock"
        ssh.run(
            f"mkdir -p {shlex.quote(public_dir)} "
            f"{shlex.quote(posixpath.dirname(lock_path))}"
        )
        ssh.put(temporary_path, data)
        validation_script = (
            "import math, os, sys; import xml.etree.ElementTree as ET; "
            "candidate = ET.parse(sys.argv[1]).getroot(); "
            "assert candidate.tag == 'Ads'; "
            "count = len(candidate.findall('Ad')); "
            "assert count == int(sys.argv[2]); "
            "previous = (ET.parse(sys.argv[3]).getroot() "
            "if os.path.isfile(sys.argv[3]) else None); "
            "previous_count = len(previous.findall('Ad')) if previous is not None else 0; "
            "minimum = math.ceil(previous_count * (1 - float(sys.argv[4]))); "
            "assert not previous_count or count >= minimum, "
            "f'feed count drop: {previous_count} -> {count}, minimum {minimum}'"
        )
        backup_profile = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "-",
            cfg.profile_name or "profile",
        ).strip(".-")[:40] or "profile"
        backup_dir = (
            "/opt/avito-bridge/state/studio-backups/"
            f"local-{backup_profile}-{uuid.uuid4().hex[:12]}"
        )
        backup_root = "/opt/avito-bridge/state/studio-backups"
        backup_prefix = f"local-{backup_profile}-"
        inner = (
            "set -eu; "
            f"python3 -c {shlex.quote(_LOCAL_BACKUP_RECOVERY_SCRIPT)} "
            f"{shlex.quote(backup_root)} {shlex.quote(backup_prefix)} "
            f"{shlex.quote(public_path)} && "
            f"python3 -c {shlex.quote(validation_script)} "
            f"{shlex.quote(temporary_path)} {result.ads_built} "
            f"{shlex.quote(public_path)} {cfg.feed.max_drop_fraction} && "
            f"python3 -c {shlex.quote(_LOCAL_BACKUP_PREPARE_SCRIPT)} "
            f"{shlex.quote(backup_dir)} {shlex.quote(public_path)} && "
            f"mv -f {shlex.quote(temporary_path)} {shlex.quote(public_path)} && "
            f"python3 -c {shlex.quote(_LOCAL_BACKUP_COMMIT_SCRIPT)} "
            f"{shlex.quote(backup_dir)} {shlex.quote(public_path)} && "
            f"(python3 -c {shlex.quote(_LOCAL_BACKUP_RETENTION_SCRIPT)} "
            f"{shlex.quote(backup_root)} {shlex.quote(backup_prefix)} 20 || true)"
        )
        command = (
            f"flock -n {shlex.quote(lock_path)} -c {shlex.quote(inner)}; "
            "rc=$?; "
            f"rm -f -- {shlex.quote(temporary_path)}; "
            "exit $rc"
        )
        ssh.run(command)
    label = cfg.profile_name or Path(config_path).stem
    return (f"profile={label} feed_uploaded={public_path} "
            f"offers_in={result.offers_in} ads_built={result.ads_built} "
            f"skipped={result.skipped} backup={backup_dir}")
