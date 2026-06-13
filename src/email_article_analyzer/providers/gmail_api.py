import base64
from collections.abc import Iterable

from email_article_analyzer.gmail import GmailMessage


def parse_gmail_message(raw_message: dict) -> GmailMessage:
    payload = raw_message.get("payload", {})
    headers = _headers_by_name(payload.get("headers", []))
    text_parts: list[str] = []
    html_parts: list[str] = []

    for part in _walk_parts(payload):
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if not data:
            continue
        decoded = _decode_body(data)
        if mime_type == "text/plain":
            text_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(decoded)

    return GmailMessage(
        message_id=raw_message.get("id", ""),
        thread_id=raw_message.get("threadId", ""),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        labels=list(raw_message.get("labelIds", [])),
        html_body="\n".join(html_parts),
        text_body="\n".join(text_parts),
    )


def _headers_by_name(headers: Iterable[dict]) -> dict[str, str]:
    return {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in headers
    }


def _walk_parts(part: dict) -> Iterable[dict]:
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def _decode_body(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii")).decode(
        "utf-8",
        errors="replace",
    )
