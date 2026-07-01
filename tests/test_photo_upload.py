from PIL import Image
from avito_studio.photo_upload import upload_manual_photo


class FakeSsh:
    def __init__(self):
        self.run_calls = []
        self.put_calls = []

    def run(self, cmd):
        self.run_calls.append(cmd)
        return ""

    def put(self, remote_path, data):
        self.put_calls.append((remote_path, data))


def test_upload_manual_photo_converts_to_jpeg_and_returns_public_url(tmp_path):
    src = tmp_path / "photo.png"
    Image.new("RGB", (4, 4), color="red").save(src)
    ssh = FakeSsh()
    url = upload_manual_photo(ssh, src, "НС-42")
    assert url == "https://splithome.ru/static/manual-photos/НС-42.jpg"
    assert len(ssh.put_calls) == 1
    remote_path, data = ssh.put_calls[0]
    assert remote_path == "/opt/oasis/staticfiles/manual-photos/НС-42.jpg"
    assert data[:2] == b"\xff\xd8"   # JPEG-магия — реально сконвертировано, не сырой PNG
    assert any("mkdir -p" in c for c in ssh.run_calls)
