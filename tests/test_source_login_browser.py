from email_article_analyzer.source_login_browser import (
    ARTICLE_CHROME_EXTRA_ARGS,
    ExistingChromeDebugReadyLauncher,
    ExistingChromeDebugTabLauncher,
    UserChromeLoginLauncher,
    create_article_chrome_ready_launcher,
    create_article_chrome_launcher,
)


def test_user_chrome_login_launcher_opens_url_with_regular_chrome_process():
    calls = []

    def fake_popen(args):
        calls.append(args)

    launcher = UserChromeLoginLauncher(
        chrome_path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        popen=fake_popen,
    )

    launcher.open_url("https://www.zacks.com/login")

    assert calls == [
        [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "https://www.zacks.com/login",
        ]
    ]


def test_user_chrome_login_launcher_can_open_with_regular_chrome_debug_profile():
    calls = []

    def fake_popen(args):
        calls.append(args)

    launcher = UserChromeLoginLauncher(
        chrome_path="chrome.exe",
        popen=fake_popen,
        extra_args=("--remote-debugging-port=9222", "--user-data-dir=data/user-chrome-profile"),
    )

    launcher.open_url("https://seekingalpha.com/article/1")

    assert calls == [
        [
            "chrome.exe",
            "--remote-debugging-port=9222",
            "--user-data-dir=data/user-chrome-profile",
            "https://seekingalpha.com/article/1",
        ]
    ]


def test_article_chrome_args_do_not_force_new_window_per_article():
    assert "--new-window" not in ARTICLE_CHROME_EXTRA_ARGS


def test_article_chrome_launcher_uses_absolute_profile_path(tmp_path):
    calls = []

    def fake_popen(args):
        calls.append(args)

    launcher = create_article_chrome_launcher(
        chrome_path="chrome.exe",
        popen=fake_popen,
        profile_path=tmp_path / "article-profile",
    )

    launcher.open_url("https://seekingalpha.com/article/1")

    assert f"--user-data-dir={tmp_path / 'article-profile'}" in calls[0]


def test_existing_debug_tab_launcher_opens_tab_through_cdp():
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    class Client:
        def get(self, url, timeout):
            calls.append(("get", url, timeout))
            return Response()

        def put(self, url, timeout):
            calls.append(("put", url, timeout))
            return Response()

    launcher = ExistingChromeDebugTabLauncher(
        cdp_url="http://127.0.0.1:9222/",
        http_client=Client(),
    )

    launcher.open_url("https://seekingalpha.com/article/1?a=b c")

    assert calls == [
        ("get", "http://127.0.0.1:9222/json/version", 3.0),
        (
            "put",
            "http://127.0.0.1:9222/json/new?https%3A%2F%2Fseekingalpha.com%2Farticle%2F1%3Fa%3Db%20c",
            3.0,
        ),
    ]


def test_existing_debug_ready_launcher_verifies_cdp_without_opening_tab():
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    class Client:
        def get(self, url, timeout):
            calls.append(("get", url, timeout))
            return Response()

    launcher = ExistingChromeDebugReadyLauncher(
        cdp_url="http://127.0.0.1:9222",
        http_client=Client(),
    )

    launcher.open_url("https://seekingalpha.com/article/1")

    assert calls == [("get", "http://127.0.0.1:9222/json/version", 3.0)]


def test_article_chrome_launcher_existing_debug_does_not_spawn_profile():
    launcher = create_article_chrome_launcher(mode="existing_debug")

    assert isinstance(launcher, ExistingChromeDebugTabLauncher)


def test_article_chrome_ready_launcher_existing_debug_does_not_open_tabs():
    launcher = create_article_chrome_ready_launcher(mode="existing_debug")

    assert isinstance(launcher, ExistingChromeDebugReadyLauncher)
