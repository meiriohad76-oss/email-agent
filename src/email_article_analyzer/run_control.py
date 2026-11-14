from threading import Lock


class RunControl:
    def __init__(self):
        self._lock = Lock()
        self._stop_requested = False
        self._active_run_id = None

    def begin_run(self) -> bool:
        with self._lock:
            if self._active_run_id is not None:
                return False
            self._active_run_id = "starting"
            self._stop_requested = False
            return True

    def set_active_run_id(self, run_id: int) -> None:
        with self._lock:
            if self._active_run_id is not None:
                self._active_run_id = run_id

    def end_run(self) -> None:
        with self._lock:
            self._active_run_id = None
            self._stop_requested = False

    def active_run_id(self):
        with self._lock:
            return self._active_run_id

    def request_stop(self) -> None:
        with self._lock:
            self._stop_requested = True

    def clear_stop(self) -> None:
        with self._lock:
            self._stop_requested = False

    def is_stop_requested(self) -> bool:
        with self._lock:
            return self._stop_requested
