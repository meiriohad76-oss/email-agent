import argparse
from collections.abc import Sequence

from email_article_analyzer.api.status import provider_status
from email_article_analyzer.config import AppConfig


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
    args = parser.parse_args(argv)
    if args.command == "setup-status":
        _print_setup_status()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
