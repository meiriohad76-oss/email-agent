from collections import deque
from dataclasses import dataclass
import threading
import time
from uuid import uuid4


@dataclass(frozen=True)
class BrowserArticleTask:
    task_id: str
    url: str


@dataclass(frozen=True)
class BrowserArticleTaskResult:
    task_id: str
    status: str
    final_url: str | None = None
    title: str | None = None
    extracted_text: str | None = None
    http_status: int | None = None
    error: str | None = None


class BrowserTaskQueue:
    def __init__(
        self,
        clock=time.monotonic,
        extension_stale_seconds: float = 30.0,
        task_lease_seconds: float = 180.0,
    ):
        self.clock = clock
        self.extension_stale_seconds = extension_stale_seconds
        self.task_lease_seconds = task_lease_seconds
        self._condition = threading.Condition()
        self._pending: deque[BrowserArticleTask] = deque()
        self._inflight: dict[str, tuple[BrowserArticleTask, float]] = {}
        self._results: dict[str, BrowserArticleTaskResult] = {}
        self._last_extension_seen_at: float | None = None

    def mark_extension_seen(self) -> None:
        with self._condition:
            self._last_extension_seen_at = self.clock()
            self._condition.notify_all()

    def is_extension_connected(self) -> bool:
        with self._condition:
            return self._is_extension_connected_locked()

    def next_task(self) -> BrowserArticleTask | None:
        with self._condition:
            self._last_extension_seen_at = self.clock()
            self._requeue_expired_leases_locked()
            if not self._pending:
                return None
            task = self._pending.popleft()
            self._inflight[task.task_id] = (task, self.clock() + self.task_lease_seconds)
            return task

    def complete_task(self, result: BrowserArticleTaskResult) -> bool:
        with self._condition:
            self._last_extension_seen_at = self.clock()
            if result.task_id not in self._inflight:
                return False
            self._inflight.pop(result.task_id, None)
            self._results[result.task_id] = result
            self._condition.notify_all()
            return True

    def submit_article_task(
        self,
        url: str,
        timeout_seconds: float = 120.0,
    ) -> BrowserArticleTaskResult:
        with self._condition:
            if not self._is_extension_connected_locked():
                raise RuntimeError("User Chrome extension is not connected")
            task = BrowserArticleTask(task_id=str(uuid4()), url=url)
            self._pending.append(task)
            self._condition.notify_all()
            deadline = self.clock() + timeout_seconds
            while True:
                result = self._results.pop(task.task_id, None)
                if result is not None:
                    return result
                self._requeue_expired_leases_locked()
                remaining = deadline - self.clock()
                if remaining <= 0:
                    self._remove_pending_locked(task.task_id)
                    self._inflight.pop(task.task_id, None)
                    raise TimeoutError("Timed out waiting for user Chrome article extraction")
                self._condition.wait(timeout=remaining)

    def _is_extension_connected_locked(self) -> bool:
        return (
            self._last_extension_seen_at is not None
            and self.clock() - self._last_extension_seen_at <= self.extension_stale_seconds
        )

    def _remove_pending_locked(self, task_id: str) -> None:
        self._pending = deque(task for task in self._pending if task.task_id != task_id)

    def _requeue_expired_leases_locked(self) -> None:
        now = self.clock()
        expired = [
            task_id
            for task_id, (_, deadline) in self._inflight.items()
            if deadline <= now
        ]
        for task_id in expired:
            task, _ = self._inflight.pop(task_id)
            if task_id not in self._results:
                self._pending.appendleft(task)
