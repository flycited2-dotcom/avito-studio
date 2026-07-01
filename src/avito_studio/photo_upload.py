"""Загрузка ручного фото для товара без фото в БД. Конвертирует в JPEG и заливает на VPS —
тот же путь/URL, что уже использует avito-bridge/scripts/apply_inbox.py::upload_photo."""
from __future__ import annotations
import io
from pathlib import Path
from PIL import Image

REMOTE_DIR = "/opt/oasis/staticfiles/manual-photos"
PUBLIC_BASE = "https://splithome.ru/static/manual-photos"


def upload_manual_photo(ssh, local_path: Path, nc_code: str) -> str:
    """ssh — объект с .run()/.put() (см. SshClient). Возвращает публичный URL фото."""
    buf = io.BytesIO()
    Image.open(local_path).convert("RGB").save(buf, "JPEG", quality=92)
    ssh.run(f"mkdir -p {REMOTE_DIR}")
    ssh.put(f"{REMOTE_DIR}/{nc_code}.jpg", buf.getvalue())
    ssh.run(f"chmod 644 {REMOTE_DIR}/{nc_code}.jpg")
    return f"{PUBLIC_BASE}/{nc_code}.jpg"
