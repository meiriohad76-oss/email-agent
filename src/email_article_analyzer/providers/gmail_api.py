import base64
from collections.abc import Iterable

from email_article_analyzer.gmail import GmailMessage


class GmailApiProvider:
    def __init__(self, service, user_id: str = "me"):
        self.service = service
        self.user_id = user_id
        self._label_cache: dict[str, str] | None = None

    def search_unread_messages(self, query: str) -> list[GmailMessage]:
        messages: list[GmailMessage] = []
        page_token = None
        while True:
            response = (
                self.service.users()
                .messages()
                .list(
                    userId=self.user_id,
                    q=query,
                    pageToken=page_token,
                    maxResults=100,
                )
                .execute()
            )
            for item in response.get("messages", []):
                raw_message = (
                    self.service.users()
                    .messages()
                    .get(userId=self.user_id, id=item["id"], format="full")
                    .execute()
                )
                messages.append(parse_gmail_message(raw_message))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return messages

    def read_message(self, message_id: str) -> GmailMessage:
        raw_message = (
            self.service.users()
            .messages()
            .get(userId=self.user_id, id=message_id, format="full")
            .execute()
        )
        return parse_gmail_message(raw_message)

    def add_label(self, message_id: str, label: str) -> None:
        label_id = self._ensure_label_id(label)
        self._modify_message(message_id, add_label_ids=[label_id], remove_label_ids=[])

    def remove_label(self, message_id: str, label: str) -> None:
        label_id = self._ensure_label_id(label)
        self._modify_message(message_id, add_label_ids=[], remove_label_ids=[label_id])

    def mark_read(self, message_id: str) -> None:
        self._modify_message(message_id, add_label_ids=[], remove_label_ids=["UNREAD"])

    def _ensure_label_id(self, label_name: str) -> str:
        labels = self._labels_by_name()
        if label_name in labels:
            return labels[label_name]
        created = (
            self.service.users()
            .labels()
            .create(userId=self.user_id, body={"name": label_name})
            .execute()
        )
        label_id = created["id"]
        labels[label_name] = label_id
        return label_id

    def _labels_by_name(self) -> dict[str, str]:
        if self._label_cache is None:
            response = self.service.users().labels().list(userId=self.user_id).execute()
            self._label_cache = {
                label["name"]: label["id"]
                for label in response.get("labels", [])
            }
        return self._label_cache

    def _modify_message(
        self,
        message_id: str,
        add_label_ids: list[str],
        remove_label_ids: list[str],
    ) -> None:
        (
            self.service.users()
            .messages()
            .modify(
                userId=self.user_id,
                id=message_id,
                body={
                    "addLabelIds": add_label_ids,
                    "removeLabelIds": remove_label_ids,
                },
            )
            .execute()
        )


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
        internal_date_ms=int(raw_message.get("internalDate") or 0),
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
