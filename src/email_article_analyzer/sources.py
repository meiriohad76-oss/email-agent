from dataclasses import dataclass
from email.utils import parseaddr
from urllib.parse import urlparse


@dataclass(frozen=True)
class TrustedSource:
    source_key: str
    display_name: str
    sender_domains: tuple[str, ...]
    article_domains: tuple[str, ...]
    login_url: str


TRUSTED_SOURCES: tuple[TrustedSource, ...] = (
    TrustedSource(
        source_key="seeking_alpha",
        display_name="Seeking Alpha",
        sender_domains=("seekingalpha.com",),
        article_domains=("seekingalpha.com", "www.seekingalpha.com"),
        login_url="https://seekingalpha.com/account/login",
    ),
    TrustedSource(
        source_key="zacks",
        display_name="Zacks",
        sender_domains=("zacks.com",),
        article_domains=("zacks.com", "www.zacks.com"),
        login_url="https://www.zacks.com/login",
    ),
    TrustedSource(
        source_key="investing",
        display_name="Investing.com",
        sender_domains=("investing.com",),
        article_domains=("investing.com", "www.investing.com"),
        login_url="https://www.investing.com/login",
    ),
)


def match_source_for_sender(sender: str) -> TrustedSource | None:
    _, address = parseaddr(sender)
    domain = address.lower().split("@")[-1] if "@" in address else sender.lower()
    for source in TRUSTED_SOURCES:
        if any(
            domain == sender_domain or domain.endswith(f".{sender_domain}")
            for sender_domain in source.sender_domains
        ):
            return source
    return None


def match_source_for_url(url: str) -> TrustedSource | None:
    host = (urlparse(url).hostname or "").lower()
    for source in TRUSTED_SOURCES:
        if any(host == domain or host.endswith(f".{domain}") for domain in source.article_domains):
            return source
    return None
