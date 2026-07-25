"""Загрузка ручного фото для товара без фото в БД. Конвертирует в JPEG и заливает на VPS —
тот же путь/URL, что уже использует avito-bridge/scripts/apply_inbox.py::upload_photo."""
from __future__ import annotations
import hashlib
import io
import logging
import re
import shlex
import uuid
from pathlib import Path
from PIL import Image

REMOTE_DIR = "/opt/oasis/staticfiles/manual-photos"
PUBLIC_BASE = "https://splithome.ru/static/manual-photos"
_SAFE_NAME = re.compile(r"^[\w-]+$", re.UNICODE)
_MAX_CODE_LENGTH = 80
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
logger = logging.getLogger(__name__)


def is_safe_nc_code(value: str) -> bool:
    """Внутренний код пригоден и как YAML-ключ, и как часть имени файла на VPS."""
    normalized = value.strip() if value else ""
    return bool(
        normalized
        and len(normalized) <= _MAX_CODE_LENGTH
        and _SAFE_NAME.fullmatch(normalized)
    )


def _jpeg_bytes(source) -> bytes:
    if isinstance(source, (str, Path)):
        if Path(source).stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Фото превышает безопасный предел размера.")
    elif hasattr(source, "getbuffer") and source.getbuffer().nbytes > MAX_SOURCE_BYTES:
        raise ValueError("Фото превышает безопасный предел размера.")
    out = io.BytesIO()
    with Image.open(source) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError(
                "Фото имеет слишком большое разрешение "
                f"(лимит {MAX_IMAGE_PIXELS:,} пикселей)."
            )
        image.convert("RGB").save(out, "JPEG", quality=92)
    return out.getvalue()


def _upload_jpeg(ssh, jpeg: bytes, nc_code: str) -> str:
    if not is_safe_nc_code(nc_code):
        raise ValueError(f"Небезопасный артикул для имени фото: {nc_code!r}")
    normalized_code = nc_code.strip()
    # Content-addressed filenames never overwrite the photo referenced by a
    # saved catalog entry.  If the later YAML save fails, the old URL and file
    # remain intact; at worst the new, unreferenced image can be collected.
    digest = hashlib.sha256(jpeg).hexdigest()
    filename = f"{normalized_code}-{digest}.jpg"
    final_path = f"{REMOTE_DIR}/{filename}"
    temporary_path = f"{REMOTE_DIR}/.{filename}.{uuid.uuid4().hex}.tmp"
    directory_q = shlex.quote(REMOTE_DIR)
    temporary_q = shlex.quote(temporary_path)
    final_q = shlex.quote(final_path)
    ssh.run(f"install -d -m 755 -- {directory_q}")
    try:
        # SFTP writes only the hidden candidate.  Promotion is a same-directory
        # rename, so an interrupted upload can never truncate the public JPEG.
        ssh.put(temporary_path, jpeg)
        ssh.run(
            f"chmod 644 -- {temporary_q} && mv -f -- {temporary_q} {final_q}"
        )
    except Exception:
        try:
            ssh.run(f"rm -f -- {temporary_q}")
        except Exception as cleanup_error:  # pragma: no cover - remote outage
            logger.warning(
                "Не удалось удалить временное фото %s: %s",
                temporary_path,
                cleanup_error,
            )
        raise
    return f"{PUBLIC_BASE}/{filename}"


def upload_manual_photo(ssh, local_path: Path, nc_code: str) -> str:
    """ssh — объект с .run()/.put() (см. SshClient). Возвращает публичный URL фото."""
    return _upload_jpeg(ssh, _jpeg_bytes(local_path), nc_code)


def upload_manual_photo_bytes(ssh, image_bytes: bytes, nc_code: str) -> str:
    """Вариант для изображения, извлечённого из XLSX без временного файла."""
    return _upload_jpeg(ssh, _jpeg_bytes(io.BytesIO(image_bytes)), nc_code)
