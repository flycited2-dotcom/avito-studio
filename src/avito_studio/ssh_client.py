"""Тонкая обёртка над SSH — тот же паттерн, что уже используется в
avito-bridge/scripts/apply_inbox.py (ssh_run/ssh_put), вынесенный в переиспользуемый класс."""
from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SshClient:
    host: str            # например, "deploy@example.test"
    key_path: str         # напр. "~/.ssh/climat_simf_deploy"
    run_timeout: int = 300
    put_timeout: int = 120

    def _base_cmd(self) -> list[str]:
        executable = shutil.which("ssh")
        if not executable:
            raise RuntimeError(
                "OpenSSH Client не найден. Включите компонент Windows "
                "«OpenSSH Client» и повторите операцию."
            )
        key = Path(self.key_path).expanduser()
        if not key.is_file():
            raise RuntimeError(
                f"SSH-ключ не найден: {key}. Откройте Настройки → SSH-подключение."
            )
        if not self.host or self.host.startswith("-") or any(
            char.isspace() or char == "\0" for char in self.host
        ):
            raise ValueError("Некорректный SSH host")
        return [executable, "-i", str(key), "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=45", self.host]

    def run(self, remote_cmd: str) -> str:
        # encoding явный: без него subprocess берёт локаль Windows (cp1251), а сервер отдаёт
        # UTF-8 с кириллицей (артикулы/бренды) — фоновый ридер падает с UnicodeDecodeError,
        # и subprocess.run молча возвращает stdout=None вместо исключения.
        # timeout на ИСПОЛНЕНИЕ (ConnectTimeout покрывает только соединение): зависшая команда
        # без него заморозила бы busy-guard тулбара навсегда. 300 с — деплой с генерацией
        # карточек реально занимает до минуты, запас втрое.
        try:
            result = subprocess.run(
                self._base_cmd() + [remote_cmd],
                timeout=self.run_timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"SSH-команда не завершилась за {self.run_timeout} с"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Не удалось запустить ssh: {exc}") from exc
        if result.returncode != 0:
            # НЕ check=True: CalledProcessError говорит только "exit status 255", а пользователю
            # в окне ошибки нужна настоящая причина ("Permission denied", "Connection timed out"…)
            raise RuntimeError((result.stderr or "").strip()
                               or f"ssh завершился с кодом {result.returncode}")
        return result.stdout or ""

    def put(self, remote_path: str, data: bytes) -> None:
        if "\0" in remote_path:
            raise ValueError("Удалённый путь содержит NUL-байт")
        command = f"cat > {shlex.quote(remote_path)}"
        try:
            result = subprocess.run(
                self._base_cmd() + [command],
                input=data,
                capture_output=True,
                timeout=self.put_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Загрузка по SSH не завершилась за {self.put_timeout} с"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Не удалось запустить ssh: {exc}") from exc
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or f"ssh завершился с кодом {result.returncode}")
