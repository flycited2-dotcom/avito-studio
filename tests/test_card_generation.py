import shlex

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
    assert shlex.quote("breeze|funai|kagami") in ssh.calls[0]


def test_generate_card_shell_quotes_untrusted_series_key():
    ssh = FakeSsh()
    malicious = 'series"; touch /tmp/injected; echo "'
    generate_card(ssh, malicious)
    assert ssh.calls[0].endswith(shlex.quote(malicious))
    assert "cards_run 'series\"; touch /tmp/injected; echo \"'" in ssh.calls[0]
