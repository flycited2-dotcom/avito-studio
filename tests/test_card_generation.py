from avito_studio.card_generation import generate_card


class FakeSsh:
    def __init__(self, output="cards: series=1 submitted=1 published=0\n"):
        self.output = output
        self.calls = []

    def run(self, cmd):
        self.calls.append(cmd)
        return self.output


def test_generate_card_runs_cards_run_with_series_key():
    ssh = FakeSsh()
    out = generate_card(ssh, "breeze|funai|kagami")
    assert out == "cards: series=1 submitted=1 published=0\n"
    assert len(ssh.calls) == 1
    assert "cards_run" in ssh.calls[0]
    assert '"breeze|funai|kagami"' in ssh.calls[0]
