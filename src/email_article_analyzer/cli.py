import argparse
from collections.abc import Sequence

from email_article_analyzer.api.status import provider_status
from email_article_analyzer.auth import create_gmail_token
from email_article_analyzer.config import AppConfig
from email_article_analyzer.repositories import RunRepository


def _print_setup_status() -> None:
    payload = provider_status(AppConfig.from_env())
    print("First-run setup status")
    print(f"Overall: {payload['overall_status']}")
    print()
    for provider_key, provider in payload["providers"].items():
        label = provider_key.replace("_", " ")
        print(f"{label}: {provider['status']}")
        for detail in provider["details"]:
            print(f"  - {detail}")
        for step in provider["setup_steps"]:
            print(f"  next: {step}")
        print()
    print("Recheck with: python -m email_article_analyzer.cli setup-status")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="email-article-analyzer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup-status", help="Print first-run setup readiness")
    subparsers.add_parser(
        "reset-analyzed-state",
        help="Clear local article analyses so Gmail messages can be analyzed again",
    )
    gmail_auth_parser = subparsers.add_parser(
        "gmail-auth",
        help="Run Gmail OAuth and write the token file",
    )
    gmail_auth_parser.add_argument("--credentials-path")
    gmail_auth_parser.add_argument("--token-path")
    args = parser.parse_args(argv)
    if args.command == "setup-status":
        _print_setup_status()
        return 0
    if args.command == "reset-analyzed-state":
        config = AppConfig.from_env()
        reset_count = RunRepository(config.database_path).reset_analyzed_state()
        suffix = "" if reset_count == 1 else "s"
        print(f"Cleared {reset_count} local article analysis row{suffix}.")
        print("Gmail labels were not changed.")
        return 0
    if args.command == "gmail-auth":
        config = AppConfig.from_env()
        token_path = create_gmail_token(
            credentials_path=args.credentials_path or config.gmail_credentials_path,
            token_path=args.token_path or config.gmail_token_path,
        )
        print(f"Gmail token saved to {token_path}")
        print("Recheck with: python -m email_article_analyzer.cli setup-status")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
