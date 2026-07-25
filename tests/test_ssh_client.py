import subprocess
from pathlib import Path

import pytest

from avito_studio.ssh_client import SshClient


@pytest.fixture(autouse=True)
def _ssh_prerequisites(monkeypatch):
    monkeypatch.setattr("avito_studio.ssh_client.shutil.which", lambda name: "ssh")
    monkeypatch.setattr("avito_studio.ssh_client.Path.is_file", lambda path: True)


def test_run_builds_correct_ssh_command(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="hello\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = SshClient(host="root@1.2.3.4", key_path="/k")
    out = client.run("echo hi")
    assert out == "hello\n"
    assert captured["cmd"] == ["ssh", "-i", str(Path("/k")), "-o", "BatchMode=yes",
                               "-o", "ConnectTimeout=45", "root@1.2.3.4", "echo hi"]
    assert captured["kwargs"]["encoding"] == "utf-8"   # иначе Windows берёт cp1251, кириллица ломает вывод


def test_run_raises_with_stderr_text_on_failure(monkeypatch):
    # раньше check=True давал "Command ... returned non-zero exit status 255" — БЕЗ причины;
    # пользователь должен видеть настоящий текст ошибки ssh (напр. "Permission denied").
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 255, stdout="",
                                           stderr="Permission denied (publickey).\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = SshClient(host="root@1.2.3.4", key_path="/k")
    with pytest.raises(RuntimeError, match="Permission denied"):
        client.run("echo hi")


def test_run_and_put_pass_execution_timeout(monkeypatch):
    # ConnectTimeout покрывает только установку соединения; зависшая КОМАНДА без timeout
    # заморозила бы busy-guard тулбара навсегда (фоновый worker никогда не вернётся)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.setdefault("timeouts", []).append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = SshClient(host="root@1.2.3.4", key_path="/k")
    client.run("echo hi")
    client.put("/tmp/f.bin", b"data")
    assert all(t and t > 0 for t in captured["timeouts"])


def test_put_raises_with_stderr_text_on_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"No space left on device\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = SshClient(host="root@1.2.3.4", key_path="/k")
    with pytest.raises(RuntimeError, match="No space left"):
        client.put("/tmp/f.bin", b"data")


def test_put_pipes_data_via_stdin(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = SshClient(host="root@1.2.3.4", key_path="/k")
    client.put("/tmp/f.bin", b"data")
    assert captured["cmd"][-1] == "cat > /tmp/f.bin"
    assert captured["input"] == b"data"


def test_put_shell_quotes_remote_path(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["remote_cmd"] = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = SshClient(host="root@1.2.3.4", key_path="/k")
    client.put("/tmp/file name; touch /tmp/pwn", b"data")
    assert captured["remote_cmd"] == "cat > '/tmp/file name; touch /tmp/pwn'"


def test_timeout_is_reported_as_actionable_runtime_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = SshClient(host="root@1.2.3.4", key_path="/k", run_timeout=7)
    with pytest.raises(RuntimeError, match="7"):
        client.run("long-running-command")


def test_missing_ssh_key_has_actionable_error(monkeypatch):
    monkeypatch.setattr("avito_studio.ssh_client.Path.is_file", lambda path: False)
    with pytest.raises(RuntimeError, match="Настройки"):
        SshClient("root@example.test", "missing-key").run("true")


def test_missing_openssh_has_actionable_error(monkeypatch):
    monkeypatch.setattr("avito_studio.ssh_client.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="OpenSSH"):
        SshClient("root@example.test", "key").run("true")
