from threading import Lock


class RunControl:
    def __init__(self):
        self._lock = Lock()
        self._stop_requested = False

    def request_stop(self) -> None:
        with self._lock:
            self._stop_requested = True

    def clear_stop(self) -> None:
        with self._lock:
            self._stop_requested = False

    def is_stop_requested(self) -> bool:
        with self._lock:
            return self._stop_requested
