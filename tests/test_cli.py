from email_article_analyzer.cli import main


class FakeCredentials:
    def to_json(self):
        return '{"token": "fake"}'


class FakeFlow:
    calls = []

    def run_local_server(self, port):
        self.calls.append(("run_local_server", port))
        return FakeCredentials()


def fake_flow_factory(credentials_path, scopes):
    FakeFlow.calls.append(("from_client_secrets_file", credentials_path, scopes))
    return FakeFlow()


def test_setup_status_cli_prints_first_run_checklist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))

    exit_code = main(["setup-status"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "First-run setup status" in output
    assert "OPENAI_API_KEY is missing" in output
    assert f"Place Gmail OAuth client credentials at {credentials_path}" in output
    assert f"Complete Gmail OAuth and save token at {token_path}" in output
    assert "python -m email_article_analyzer.cli setup-status" in output


def test_gmail_auth_cli_creates_token_file(tmp_path, monkeypatch, capsys):
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    FakeFlow.calls = []
    monkeypatch.setattr(
        "email_article_analyzer.auth.InstalledAppFlow.from_client_secrets_file",
        fake_flow_factory,
    )

    exit_code = main(
        [
            "gmail-auth",
            "--credentials-path",
            str(credentials_path),
            "--token-path",
            str(token_path),
        ]
    )

    assert exit_code == 0
    assert token_path.read_text(encoding="utf-8") == '{"token": "fake"}'
    assert FakeFlow.calls[0][0] == "from_client_secrets_file"
    assert FakeFlow.calls[0][1] == str(credentials_path)
    assert "https://www.googleapis.com/auth/gmail.modify" in FakeFlow.calls[0][2]
    assert FakeFlow.calls[1] == ("run_local_server", 0)
    assert str(token_path) in capsys.readouterr().out


def test_first_run_setup_doc_has_required_steps():
    doc = open("docs/first-run-setup.md", encoding="utf-8").read()

    assert "OPENAI_API_KEY" in doc
    assert "POLYGON_API_KEY" in doc
    assert "GMAIL_CREDENTIALS_PATH" in doc
    assert "GMAIL_TOKEN_PATH" in doc
    assert "python -m email_article_analyzer.cli gmail-auth" in doc
    assert "python -m email_article_analyzer.cli setup-status" in doc
    assert "python scripts/smoke_live_product.py" in doc
    assert "python -m uvicorn email_article_analyzer.main:app --host 127.0.0.1 --port 8000" in doc
