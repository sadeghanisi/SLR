"""Explicit runtime ownership for the two WebApp background workflows."""

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScreeningRuntimeState:
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    progress: list[dict] = field(default_factory=list)
    progress_lock: Any = field(default_factory=threading.Lock)
    results: list[dict] = field(default_factory=list)
    error: str = ""

    def reset_for_start(self) -> None:
        self.stop_event.clear()
        self.progress = []
        self.results = []
        self.error = ""

    def clear(self) -> None:
        self.thread = None
        self.reset_for_start()


@dataclass
class ProcessingRuntimeState:
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    progress: list[dict] = field(default_factory=list)
    progress_lock: Any = field(default_factory=threading.Lock)
    automation: Any = None
    summary: Any = None
    error: str = ""
    report_errors: list[str] = field(default_factory=list)
    reports: dict = field(default_factory=dict)

    def reset_for_start(self) -> None:
        self.stop_event.clear()
        self.progress = []
        self.summary = None
        self.error = ""
        self.report_errors = []
        self.reports = {}

    def clear(self) -> None:
        self.thread = None
        self.automation = None
        self.reset_for_start()


def initialize(session: dict) -> None:
    session["screening_runtime"] = ScreeningRuntimeState()
    session["processing_runtime"] = ProcessingRuntimeState()
    session["event_stream_job"] = None


def screening(session: dict) -> ScreeningRuntimeState:
    return session["screening_runtime"]


def processing(session: dict) -> ProcessingRuntimeState:
    return session["processing_runtime"]


def event_stream(session: dict, active_job: str | None) -> ScreeningRuntimeState | ProcessingRuntimeState:
    kind = (
        active_job
        if active_job in {"screening", "processing"}
        else session.get("event_stream_job")
    )
    return screening(session) if kind == "screening" else processing(session)
