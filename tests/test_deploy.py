import io
import tarfile
from pathlib import Path
from avito_studio.deploy import deploy_and_rebuild


class FakeSsh:
    def __init__(self):
        self.put_calls = []
        self.run_calls = []

    def put(self, remote_path, data):
        self.put_calls.append((remote_path, data))

    def run(self, cmd):
        self.run_calls.append(cmd)
        return "ok\n"


def test_deploy_and_rebuild_packages_config_and_descriptions_and_runs_remote(tmp_path):
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)
    (bridge_root / "avito-descriptions" / "manifest.json").write_text("{}", encoding="utf-8")

    ssh = FakeSsh()
    out = deploy_and_rebuild(bridge_root, ssh)

    assert out == "ok\n"
    assert len(ssh.put_calls) == 1
    remote_path, data = ssh.put_calls[0]
    assert remote_path == "/tmp/studio_deploy.tgz"
    assert data.startswith(b"\x1f\x8b")             # gzip-магия — реально запаковано
    assert len(ssh.run_calls) == 1
    assert "cards_run" in ssh.run_calls[0]
    assert "systemctl start avito-bridge.service" in ssh.run_calls[0]


def test_deploy_includes_profiles_dir_when_present(tmp_path):
    # правки YAML профилей (галочки венков) обязаны уезжать на сервер вместе с config/ —
    # иначе «Опубликовать» для второго бизнеса молча теряет изменения
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)
    (bridge_root / "profiles").mkdir(parents=True)
    (bridge_root / "profiles" / "wreaths.yaml").write_text("profile: {name: wreaths}\n", encoding="utf-8")

    ssh = FakeSsh()
    deploy_and_rebuild(bridge_root, ssh)

    _, data = ssh.put_calls[0]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
    assert "profiles/wreaths.yaml" in names


def test_deploy_without_profiles_dir_still_works(tmp_path):
    # старый checkout без profiles/ (или кондиционерный-только) не должен ломать публикацию
    bridge_root = tmp_path / "avito-bridge"
    (bridge_root / "config").mkdir(parents=True)
    (bridge_root / "config" / "config.yaml").write_text("catalog: {}\n", encoding="utf-8")
    (bridge_root / "avito-descriptions").mkdir(parents=True)

    ssh = FakeSsh()
    out = deploy_and_rebuild(bridge_root, ssh)
    assert out == "ok\n"
