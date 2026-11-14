from __future__ import annotations

from copy import deepcopy
from threading import Event, Lock, Thread
from typing import Any, Callable


class BulkResearchExtractionManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._state = self._idle_state()

    def start(
        self,
        run_id: int,
        tickers: list[str],
        worker: Callable[[str], dict[str, int]],
        job_type: str = "bulk_extraction",
        requested_records: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Bulk research extraction is already running")
            self._stop.clear()
            self._state = {
                "status": "running",
                "run_id": run_id,
                "total": len(tickers),
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "current_ticker": None,
                "completed_tickers": [],
                "failures": [],
                "message": "Bulk extraction started",
                "job_type": job_type,
                "requested_records": requested_records,
                "attempted_records": 0,
                "saved_records": 0,
                "failed_records": 0,
            }
            self._thread = Thread(
                target=self._run,
                args=(tickers, worker, job_type),
                name=f"bulk-research-{run_id}",
                daemon=True,
            )
            self._thread.start()
            return deepcopy(self._state)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def request_stop(self) -> dict[str, Any]:
        with self._lock:
            if self._state["status"] not in {"running", "stopping"}:
                return deepcopy(self._state)
            self._stop.set()
            self._state["status"] = "stopping"
            self._state["message"] = "Stop requested; the current company will finish first"
            return deepcopy(self._state)

    def _run(
        self,
        tickers: list[str],
        worker: Callable[[str], dict[str, int]],
        job_type: str,
    ) -> None:
        for ticker in tickers:
            if self._stop.is_set():
                break
            with self._lock:
                self._state["current_ticker"] = ticker
                self._state["message"] = f"Extracting {ticker}"
            try:
                result = worker(ticker)
                attempted = int(result.get("attempted", 0))
                saved = int(result.get("saved", 0))
                failed = int(result.get("failed", 0))
                with self._lock:
                    self._state["attempted_records"] += attempted
                    self._state["saved_records"] += saved
                    self._state["failed_records"] += failed
                incomplete = (
                    attempted <= 0
                    or (job_type == "source_issue_retry" and saved <= 0)
                    or (job_type != "source_issue_retry" and saved <= 1 and failed >= 5)
                )
                if incomplete:
                    raise RuntimeError(
                        f"Paid-page extraction did not complete (attempted={attempted}, saved={saved}, failed={failed})"
                    )
            except Exception as exc:
                with self._lock:
                    self._state["failed"] += 1
                    self._state["failures"].append({"ticker": ticker, "error": str(exc)})
            else:
                with self._lock:
                    self._state["succeeded"] += 1
                    self._state["completed_tickers"].append(ticker)
            finally:
                with self._lock:
                    self._state["processed"] += 1

        with self._lock:
            stopped = self._stop.is_set()
            self._state["status"] = "stopped" if stopped else "completed"
            self._state["current_ticker"] = None
            self._state["message"] = (
                "Bulk extraction stopped; start again to resume remaining companies"
                if stopped
                else "Bulk extraction completed"
            )

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "status": "idle",
            "run_id": None,
            "total": 0,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "current_ticker": None,
            "completed_tickers": [],
            "failures": [],
            "message": "No bulk extraction is running",
            "job_type": None,
            "requested_records": None,
            "attempted_records": 0,
            "saved_records": 0,
            "failed_records": 0,
        }
