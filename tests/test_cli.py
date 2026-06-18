from email_article_analyzer.cli import main


def test_setup_status_cli_prints_first_run_checklist(tmp_path, monkeypatch, capsys):
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


def test_first_run_setup_doc_has_required_steps():
    doc = open("docs/first-run-setup.md", encoding="utf-8").read()

    assert "OPENAI_API_KEY" in doc
    assert "POLYGON_API_KEY" in doc
    assert "GMAIL_CREDENTIALS_PATH" in doc
    assert "GMAIL_TOKEN_PATH" in doc
    assert "python -m email_article_analyzer.cli setup-status" in doc
