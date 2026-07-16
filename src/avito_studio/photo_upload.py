"""Загрузка ручного фото для товара без фото в БД. Конвертирует в JPEG и заливает на VPS —
тот же путь/URL, что уже использует avito-bridge/scripts/apply_inbox.py::upload_photo."""
from __future__ import annotations
import io
import re
from pathlib import Path
from PIL import Image

REMOTE_DIR = "/opt/oasis/staticfiles/manual-photos"
PUBLIC_BASE = "https://splithome.ru/static/manual-photos"
_SAFE_NAME = re.compile(r"^[\w-]+$", re.UNICODE)


def _jpeg_bytes(source) -> bytes:
    out = io.BytesIO()
    with Image.open(source) as image:
        image.convert("RGB").save(out, "JPEG", quality=92)
    return out.getvalue()


def _upload_jpeg(ssh, jpeg: bytes, nc_code: str) -> str:
    if not _SAFE_NAME.fullmatch(nc_code):
        raise ValueError(f"Небезопасный артикул для имени фото: {nc_code!r}")
    ssh.run(f"mkdir -p {REMOTE_DIR}")
    ssh.put(f"{REMOTE_DIR}/{nc_code}.jpg", jpeg)
    ssh.run(f"chmod 644 {REMOTE_DIR}/{nc_code}.jpg")
    return f"{PUBLIC_BASE}/{nc_code}.jpg"


def upload_manual_photo(ssh, local_path: Path, nc_code: str) -> str:
    """ssh — объект с .run()/.put() (см. SshClient). Возвращает публичный URL фото."""
    return _upload_jpeg(ssh, _jpeg_bytes(local_path), nc_code)


def upload_manual_photo_bytes(ssh, image_bytes: bytes, nc_code: str) -> str:
    """Вариант для изображения, извлечённого из XLSX без временного файла."""
    return _upload_jpeg(ssh, _jpeg_bytes(io.BytesIO(image_bytes)), nc_code)
