from email.message import EmailMessage
import base64


def own_address(service) -> str:
    return service.users().getProfile(userId="me").execute()["emailAddress"]


def send_email(
    service,
    *,
    to: str,
    subject: str,
    body: str,
    attachment: tuple[str, bytes] | None = None,
) -> str:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if attachment is not None:
        filename, data = attachment
        message.add_attachment(data, maintype="application", subtype="pdf", filename=filename)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return str(sent["id"])
