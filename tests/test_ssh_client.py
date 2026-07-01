import subprocess
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
    assert captured["kwargs"]["check"] is True
    assert captured["kwargs"]["encoding"] == "utf-8"   # иначе Windows берёт cp1251, кириллица ломает вывод


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
