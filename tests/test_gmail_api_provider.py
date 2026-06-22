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

    def list(self, userId, q, pageToken=None, maxResults=None):
        self.service.calls.append(("messages.list", userId, q, pageToken, maxResults))
        if self.service.pages:
            return FakeExecute(self.service.pages.pop(0))
        return FakeExecute({"messages": [{"id": message_id} for message_id in self.service.messages]})

    def get(self, userId, id, format):
        self.service.calls.append(("messages.get", userId, id, format))
        return FakeExecute(self.service.messages[id])

    def modify(self, userId, id, body):
        self.service.calls.append(("messages.modify", userId, id, body))
        return FakeExecute({"id": id})


class FakeLabels:
    def __init__(self, service):
        self.service = service

    def list(self, userId):
        self.service.calls.append(("labels.list", userId))
        return FakeExecute({"labels": self.service.labels})

    def create(self, userId, body):
        self.service.calls.append(("labels.create", userId, body))
        label = {"id": f"Label_{len(self.service.labels) + 1}", "name": body["name"]}
        self.service.labels.append(label)
        return FakeExecute(label)


class FakeUsers:
    def __init__(self, service):
        self.service = service

    def messages(self):
        return FakeMessages(self.service)

    def labels(self):
        return FakeLabels(self.service)


class FakeGmailService:
    def __init__(self, messages, labels=None, pages=None):
        self.messages = messages
        self.labels = labels or []
        self.pages = list(pages or [])
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
    assert ("messages.list", "me", "is:unread", None, 100) in service.calls
    assert ("messages.get", "me", "msg-1", "full") in service.calls


def test_gmail_api_provider_reads_all_search_result_pages():
    first_message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["UNREAD"],
        "payload": {"headers": [], "body": {"data": encoded("First")}, "mimeType": "text/plain"},
    }
    second_message = {
        "id": "msg-2",
        "threadId": "thread-2",
        "labelIds": ["UNREAD"],
        "payload": {"headers": [], "body": {"data": encoded("Second")}, "mimeType": "text/plain"},
    }
    service = FakeGmailService(
        messages={"msg-1": first_message, "msg-2": second_message},
        pages=[
            {"messages": [{"id": "msg-1"}], "nextPageToken": "page-2"},
            {"messages": [{"id": "msg-2"}]},
        ],
    )
    provider = GmailApiProvider(service=service)

    messages = provider.search_unread_messages("is:unread")

    assert [message.message_id for message in messages] == ["msg-1", "msg-2"]
    assert ("messages.list", "me", "is:unread", None, 100) in service.calls
    assert ("messages.list", "me", "is:unread", "page-2", 100) in service.calls


def test_gmail_api_provider_stops_after_max_results():
    first_message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["UNREAD"],
        "payload": {"headers": [], "body": {"data": encoded("First")}, "mimeType": "text/plain"},
    }
    second_message = {
        "id": "msg-2",
        "threadId": "thread-2",
        "labelIds": ["UNREAD"],
        "payload": {"headers": [], "body": {"data": encoded("Second")}, "mimeType": "text/plain"},
    }
    service = FakeGmailService(
        messages={"msg-1": first_message, "msg-2": second_message},
        pages=[
            {"messages": [{"id": "msg-1"}], "nextPageToken": "page-2"},
            {"messages": [{"id": "msg-2"}]},
        ],
    )
    provider = GmailApiProvider(service=service)

    messages = provider.search_unread_messages("is:unread", max_results=1)

    assert [message.message_id for message in messages] == ["msg-1"]
    assert ("messages.list", "me", "is:unread", None, 1) in service.calls
    assert ("messages.list", "me", "is:unread", "page-2", 1) not in service.calls


def test_gmail_api_provider_iterates_messages_lazily():
    first_message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["UNREAD"],
        "payload": {"headers": [], "body": {"data": encoded("First")}, "mimeType": "text/plain"},
    }
    second_message = {
        "id": "msg-2",
        "threadId": "thread-2",
        "labelIds": ["UNREAD"],
        "payload": {"headers": [], "body": {"data": encoded("Second")}, "mimeType": "text/plain"},
    }
    service = FakeGmailService(
        messages={"msg-1": first_message, "msg-2": second_message},
        pages=[
            {"messages": [{"id": "msg-1"}], "nextPageToken": "page-2"},
            {"messages": [{"id": "msg-2"}]},
        ],
    )
    provider = GmailApiProvider(service=service)
    iterator = provider.iter_unread_messages("is:unread", max_results=2, page_size=1)

    first = next(iterator)

    assert first.message_id == "msg-1"
    assert ("messages.list", "me", "is:unread", None, 1) in service.calls
    assert ("messages.get", "me", "msg-1", "full") in service.calls
    assert ("messages.list", "me", "is:unread", "page-2", 1) not in service.calls

    second = next(iterator)

    assert second.message_id == "msg-2"
    assert ("messages.list", "me", "is:unread", "page-2", 1) in service.calls


def test_gmail_api_provider_reads_message_by_id():
    raw_message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["UNREAD"],
        "payload": {
            "headers": [{"name": "Subject", "value": "Story"}],
            "body": {"data": encoded("Plain text")},
            "mimeType": "text/plain",
        },
    }
    service = FakeGmailService(messages={"msg-1": raw_message})
    provider = GmailApiProvider(service=service)

    message = provider.read_message("msg-1")

    assert message.message_id == "msg-1"
    assert message.subject == "Story"
    assert ("messages.get", "me", "msg-1", "full") in service.calls


def test_gmail_api_provider_adds_existing_label_by_name():
    service = FakeGmailService(messages={}, labels=[{"id": "Label_1", "name": "Analyzed"}])
    provider = GmailApiProvider(service=service)

    provider.add_label("msg-1", "Analyzed")

    assert ("labels.list", "me") in service.calls
    assert (
        "messages.modify",
        "me",
        "msg-1",
        {"addLabelIds": ["Label_1"], "removeLabelIds": []},
    ) in service.calls


def test_gmail_api_provider_creates_missing_label_before_adding():
    service = FakeGmailService(messages={}, labels=[])
    provider = GmailApiProvider(service=service)

    provider.add_label("msg-1", "Analysis Failed")

    assert ("labels.create", "me", {"name": "Analysis Failed"}) in service.calls
    assert (
        "messages.modify",
        "me",
        "msg-1",
        {"addLabelIds": ["Label_1"], "removeLabelIds": []},
    ) in service.calls


def test_gmail_api_provider_removes_label_and_marks_read():
    service = FakeGmailService(messages={}, labels=[{"id": "Label_2", "name": "Analysis Failed"}])
    provider = GmailApiProvider(service=service)

    provider.remove_label("msg-1", "Analysis Failed")
    provider.mark_read("msg-1")

    assert (
        "messages.modify",
        "me",
        "msg-1",
        {"addLabelIds": [], "removeLabelIds": ["Label_2"]},
    ) in service.calls
    assert (
        "messages.modify",
        "me",
        "msg-1",
        {"addLabelIds": [], "removeLabelIds": ["UNREAD"]},
    ) in service.calls


def test_gmail_api_provider_resets_processing_labels_and_marks_unread():
    service = FakeGmailService(
        messages={"msg-1": {}, "msg-2": {}},
        labels=[
            {"id": "Label_1", "name": "Analyzed"},
            {"id": "Label_2", "name": "Analysis Failed"},
        ],
        pages=[{"messages": [{"id": "msg-1"}, {"id": "msg-2"}]}],
    )
    provider = GmailApiProvider(service=service)

    reset_count = provider.reset_processing_labels(
        query='label:Analyzed OR label:"Analysis Failed"',
        label_names=["Analyzed", "Analysis Failed"],
        mark_unread=True,
        max_results=50,
    )

    assert reset_count == 2
    assert (
        "messages.list",
        "me",
        'label:Analyzed OR label:"Analysis Failed"',
        None,
        50,
    ) in service.calls
    assert (
        "messages.modify",
        "me",
        "msg-1",
        {"addLabelIds": ["UNREAD"], "removeLabelIds": ["Label_1", "Label_2"]},
    ) in service.calls
    assert (
        "messages.modify",
        "me",
        "msg-2",
        {"addLabelIds": ["UNREAD"], "removeLabelIds": ["Label_1", "Label_2"]},
    ) in service.calls
