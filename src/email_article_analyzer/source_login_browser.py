from pathlib import Path
import os
import shutil
import subprocess
import sys


ARTICLE_CHROME_EXTRA_ARGS = (
    "--remote-debugging-port=9222",
    "--no-first-run",
)


class UserChromeLoginLauncher:
    def __init__(
        self,
        chrome_path: str | None = None,
        popen=None,
        extra_args: tuple[str, ...] = (),
    ):
        self.chrome_path = chrome_path
        self.popen = popen or subprocess.Popen
        self.extra_args = extra_args

    def open_url(self, url: str) -> None:
        chrome_path = self.chrome_path or find_chrome_executable()
        if chrome_path is None:
            raise RuntimeError("Google Chrome was not found on this machine")
        self.popen([chrome_path, *self.extra_args, url])


def create_article_chrome_launcher(
    chrome_path: str | None = None,
    popen=None,
    profile_path: str | Path = "data/user-chrome-profile",
) -> UserChromeLoginLauncher:
    resolved_profile_path = Path(profile_path).resolve()
    return UserChromeLoginLauncher(
        chrome_path=chrome_path,
        popen=popen,
        extra_args=(
            *ARTICLE_CHROME_EXTRA_ARGS,
            f"--user-data-dir={resolved_profile_path}",
        ),
    )


def find_chrome_executable() -> str | None:
    for command in ("chrome", "chrome.exe", "google-chrome", "google-chrome-stable"):
        path = shutil.which(command)
        if path:
            return path

    for candidate in _platform_chrome_candidates():
        if candidate.exists():
            return str(candidate)
    return None


def _platform_chrome_candidates() -> list[Path]:
    if sys.platform.startswith("win"):
        roots = [
            os.environ.get("LOCALAPPDATA"),
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
        ]
        return [
            Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
            for root in roots
            if root
        ]
    if sys.platform == "darwin":
        return [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    return [
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/chromium"),
    ]
