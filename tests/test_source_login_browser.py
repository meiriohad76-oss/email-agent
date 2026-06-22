from email_article_analyzer.source_login_browser import UserChromeLoginLauncher


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
