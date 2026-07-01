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
        result = subprocess.run(self._base_cmd() + [remote_cmd],
                                capture_output=True, text=True, check=True)
        return result.stdout

    def put(self, remote_path: str, data: bytes) -> None:
        subprocess.run(self._base_cmd() + [f"cat > {remote_path}"], input=data, check=True)
