from email_article_analyzer.cli import main
from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository


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


def test_reset_analyzed_state_cli_clears_local_skip_state(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "app.db"
    initialize_database(str(db_path))
    gmail_repo = GmailDiscoveryRepository(str(db_path))
    run_repo = RunRepository(str(db_path))
    gmail_row_id = gmail_repo.save_message(
        run_id=run_repo.create_run("gpt-extract", "gpt-summary"),
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=gmail_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Done.",
        stance="hold",
        confidence=0.8,
        supporting_evidence=["Evidence"],
        mentioned_tickers=["AAPL"],
        raw_response={},
    )
    monkeypatch.setenv("APP_DATABASE_PATH", str(db_path))

    exit_code = main(["reset-analyzed-state"])

    assert exit_code == 0
    assert RunRepository(str(db_path)).has_analyzed_gmail_message("msg-1") is False
    output = capsys.readouterr().out
    assert "Cleared 1 local article analysis row" in output
    assert "Gmail labels were not changed" in output


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
