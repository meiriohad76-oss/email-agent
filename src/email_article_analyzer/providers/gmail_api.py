import base64
from collections.abc import Iterable

from email_article_analyzer.gmail import GmailMessage


class GmailApiProvider:
    def __init__(self, service, user_id: str = "me"):
        self.service = service
        self.user_id = user_id
        self._label_cache: dict[str, str] | None = None

    def search_unread_messages(
        self,
        query: str,
        max_results: int | None = None,
    ) -> list[GmailMessage]:
        return list(
            self.iter_unread_messages(
                query=query,
                max_results=max_results,
                page_size=100,
            )
        )

    def iter_unread_messages(
        self,
        query: str,
        max_results: int | None = None,
        page_size: int = 10,
    ):
        emitted = 0
        page_token = None
        while True:
            request_page_size = min(max_results - emitted, page_size) if max_results else page_size
            if request_page_size <= 0:
                break
            response = (
                self.service.users()
                .messages()
                .list(
                    userId=self.user_id,
                    q=query,
                    pageToken=page_token,
                    maxResults=request_page_size,
                )
                .execute()
            )
            for item in response.get("messages", []):
                if max_results is not None and emitted >= max_results:
                    break
                raw_message = (
                    self.service.users()
                    .messages()
                    .get(userId=self.user_id, id=item["id"], format="full")
                    .execute()
                )
                emitted += 1
                yield parse_gmail_message(raw_message)
            page_token = response.get("nextPageToken")
            if not page_token or (max_results is not None and emitted >= max_results):
                break

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

    def reset_processing_labels(
        self,
        query: str,
        label_names: list[str],
        mark_unread: bool,
        max_results: int | None = None,
    ) -> int:
        labels = self._labels_by_name()
        remove_label_ids = [
            labels[label_name]
            for label_name in label_names
            if label_name in labels
        ]
        if not remove_label_ids:
            return 0

        reset_count = 0
        for message_id in self._iter_message_ids(query=query, max_results=max_results):
            self._modify_message(
                message_id,
                add_label_ids=["UNREAD"] if mark_unread else [],
                remove_label_ids=remove_label_ids,
            )
            reset_count += 1
        return reset_count

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

    def _iter_message_ids(self, query: str, max_results: int | None = None):
        emitted = 0
        page_token = None
        while True:
            request_page_size = min(max_results - emitted, 100) if max_results else 100
            if request_page_size <= 0:
                break
            response = (
                self.service.users()
                .messages()
                .list(
                    userId=self.user_id,
                    q=query,
                    pageToken=page_token,
                    maxResults=request_page_size,
                )
                .execute()
            )
            for item in response.get("messages", []):
                if max_results is not None and emitted >= max_results:
                    break
                emitted += 1
                yield item["id"]
            page_token = response.get("nextPageToken")
            if not page_token or (max_results is not None and emitted >= max_results):
                break

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
