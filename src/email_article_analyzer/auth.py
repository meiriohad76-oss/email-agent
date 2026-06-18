from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def create_gmail_token(
    credentials_path: str,
    token_path: str,
    scopes: list[str] | None = None,
) -> str:
    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_path,
        scopes or GMAIL_SCOPES,
    )
    credentials = flow.run_local_server(port=0)
    destination = Path(token_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(credentials.to_json(), encoding="utf-8")
    return str(destination)
