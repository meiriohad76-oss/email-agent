import threading

from fastapi.testclient import TestClient

from email_article_analyzer.browser_tasks import BrowserArticleTaskResult, BrowserTaskQueue


def test_sa_export_task_kind_reaches_extension_and_result_returns():
    queue = BrowserTaskQueue()
    queue.mark_extension_seen()
    out = {}

    def submit():
        out["result"] = queue.submit_article_task("https://seekingalpha.com/x", timeout_seconds=5, kind="sa_export")

    t = threading.Thread(target=submit)
    t.start()
    task = None
    for _ in range(100):
        task = queue.next_task()
        if task:
            break
        threading.Event().wait(0.01)
    assert task is not None and task.kind == "sa_export"
    queue.complete_task(BrowserArticleTaskResult(task_id=task.task_id, status="success", extracted_text="UEsDBA=="))
    t.join(5)
    assert out["result"].extracted_text == "UEsDBA=="


def test_default_task_kind_is_article():
    queue = BrowserTaskQueue()
    queue.mark_extension_seen()
    threading.Thread(target=lambda: _swallow(queue), daemon=True).start()
    for _ in range(100):
        task = queue.next_task()
        if task:
            break
        threading.Event().wait(0.01)
    assert task.kind == "article"


def _swallow(queue):
    try:
        queue.submit_article_task("https://example.com", timeout_seconds=1)
    except TimeoutError:
        pass


def test_sa_export_endpoint_rejects_non_numeric_id():
    from email_article_analyzer.api.browser_tasks import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    app.state.browser_task_queue = BrowserTaskQueue()
    r = TestClient(app).post("/api/browser-tasks/sa-export", json={"portfolio_id": "1;rm"})
    assert r.json()["status"] == "failed"
