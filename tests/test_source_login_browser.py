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
