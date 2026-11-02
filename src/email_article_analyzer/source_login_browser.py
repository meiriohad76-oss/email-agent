from pathlib import Path
import os
import shutil
import subprocess
import sys
from urllib.parse import quote

import httpx


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


class ExistingChromeDebugReadyLauncher:
    def __init__(
        self,
        cdp_url: str = "http://127.0.0.1:9222",
        http_client=None,
        timeout_seconds: float = 3.0,
    ):
        self.cdp_url = cdp_url.rstrip("/")
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds

    def open_url(self, url: str) -> None:
        self._assert_debug_session()

    def _assert_debug_session(self) -> None:
        try:
            response = self.http_client.get(
                f"{self.cdp_url}/json/version",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                "Chrome debug session is not available. Close Chrome and start it with "
                "--remote-debugging-port=9222, then retry the run."
            ) from exc


class ExistingChromeDebugTabLauncher(ExistingChromeDebugReadyLauncher):
    def open_url(self, url: str) -> None:
        self._assert_debug_session()
        encoded_url = quote(url, safe="")
        response = self.http_client.put(
            f"{self.cdp_url}/json/new?{encoded_url}",
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()


def create_article_chrome_launcher(
    chrome_path: str | None = None,
    popen=None,
    profile_path: str | Path = "data/user-chrome-profile",
    mode: str = "app_profile",
    cdp_url: str = "http://127.0.0.1:9222",
) -> UserChromeLoginLauncher:
    if mode == "existing_debug":
        return ExistingChromeDebugTabLauncher(cdp_url=cdp_url)
    resolved_profile_path = Path(profile_path).resolve()
    return UserChromeLoginLauncher(
        chrome_path=chrome_path,
        popen=popen,
        extra_args=(
            *ARTICLE_CHROME_EXTRA_ARGS,
            f"--user-data-dir={resolved_profile_path}",
        ),
    )


def create_article_chrome_ready_launcher(
    chrome_path: str | None = None,
    popen=None,
    profile_path: str | Path = "data/user-chrome-profile",
    mode: str = "app_profile",
    cdp_url: str = "http://127.0.0.1:9222",
):
    if mode == "existing_debug":
        return ExistingChromeDebugReadyLauncher(cdp_url=cdp_url)
    return create_article_chrome_launcher(
        chrome_path=chrome_path,
        popen=popen,
        profile_path=profile_path,
        mode=mode,
        cdp_url=cdp_url,
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
