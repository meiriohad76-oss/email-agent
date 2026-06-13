import base64

from email_article_analyzer.providers.gmail_api import GmailApiProvider, parse_gmail_message


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


class FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeMessages:
    def __init__(self, service):
        self.service = service

    def list(self, userId, q):
        self.service.calls.append(("messages.list", userId, q))
        return FakeExecute({"messages": [{"id": message_id} for message_id in self.service.messages]})

    def get(self, userId, id, format):
        self.service.calls.append(("messages.get", userId, id, format))
        return FakeExecute(self.service.messages[id])


class FakeUsers:
    def __init__(self, service):
        self.service = service

    def messages(self):
        return FakeMessages(self.service)


class FakeGmailService:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def users(self):
        return FakeUsers(self)


def test_parse_gmail_message_extracts_headers_labels_and_bodies():
    payload = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["UNREAD", "CATEGORY_UPDATES"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Seeking Alpha <alerts@seekingalpha.com>"},
                {"name": "Subject", "value": "Main Story"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": encoded("Plain body https://seekingalpha.com/article/1")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded("<h1><a href='https://seekingalpha.com/article/1'>Story</a></h1>")},
                },
            ],
        },
    }

    message = parse_gmail_message(payload)

    assert message.message_id == "msg-1"
    assert message.thread_id == "thread-1"
    assert message.sender == "Seeking Alpha <alerts@seekingalpha.com>"
    assert message.subject == "Main Story"
    assert message.labels == ["UNREAD", "CATEGORY_UPDATES"]
    assert "Plain body" in message.text_body
    assert "<h1>" in message.html_body


def test_parse_gmail_message_handles_single_body_part():
    payload = {
        "id": "msg-2",
        "threadId": "thread-2",
        "labelIds": [],
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "No sender"}],
            "body": {"data": encoded("Only plain text")},
        },
    }

    message = parse_gmail_message(payload)

    assert message.sender == ""
    assert message.subject == "No sender"
    assert message.text_body == "Only plain text"
    assert message.html_body == ""


def test_gmail_api_provider_searches_and_reads_messages():
    raw_message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["UNREAD"],
        "payload": {
            "headers": [{"name": "From", "value": "alerts@seekingalpha.com"}],
            "body": {"data": encoded("Plain text")},
            "mimeType": "text/plain",
        },
    }
    service = FakeGmailService(messages={"msg-1": raw_message})
    provider = GmailApiProvider(service=service)

    messages = provider.search_unread_messages("is:unread")

    assert [message.message_id for message in messages] == ["msg-1"]
    assert ("messages.list", "me", "is:unread") in service.calls
    assert ("messages.get", "me", "msg-1", "full") in service.calls
