"""Тонкая обёртка над SSH — тот же паттерн, что уже используется в
avito-bridge/scripts/apply_inbox.py (ssh_run/ssh_put), вынесенный в переиспользуемый класс."""
from __future__ import annotations
import subprocess
from dataclasses import dataclass


@dataclass
class SshClient:
    host: str            # напр. "root@213.109.202.45"
    key_path: str         # напр. "~/.ssh/climat_simf_deploy"

    def _base_cmd(self) -> list[str]:
        return ["ssh", "-i", self.key_path, "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=45", self.host]

    def run(self, remote_cmd: str) -> str:
        # encoding явный: без него subprocess берёт локаль Windows (cp1251), а сервер отдаёт
        # UTF-8 с кириллицей (артикулы/бренды) — фоновый ридер падает с UnicodeDecodeError,
        # и subprocess.run молча возвращает stdout=None вместо исключения.
        # timeout на ИСПОЛНЕНИЕ (ConnectTimeout покрывает только соединение): зависшая команда
        # без него заморозила бы busy-guard тулбара навсегда. 300 с — деплой с генерацией
        # карточек реально занимает до минуты, запас втрое.
        result = subprocess.run(self._base_cmd() + [remote_cmd], timeout=300,
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            # НЕ check=True: CalledProcessError говорит только "exit status 255", а пользователю
            # в окне ошибки нужна настоящая причина ("Permission denied", "Connection timed out"…)
            raise RuntimeError((result.stderr or "").strip()
                               or f"ssh завершился с кодом {result.returncode}")
        return result.stdout

    def put(self, remote_path: str, data: bytes) -> None:
        result = subprocess.run(self._base_cmd() + [f"cat > {remote_path}"],
                                input=data, capture_output=True, timeout=120)
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or f"ssh завершился с кодом {result.returncode}")
