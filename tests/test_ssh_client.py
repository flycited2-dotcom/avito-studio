import subprocess
import pytest
from avito_studio.ssh_client import SshClient


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
    assert captured["cmd"] == ["ssh", "-i", "/k", "-o", "BatchMode=yes",
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
