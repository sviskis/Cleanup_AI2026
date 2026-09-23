"""GUI task bridge tests: worker thread, event queue, log handler - no display."""

from __future__ import annotations

import logging
import time

from pdf_ai_batch.gui import tasks


def test_event_bus_keeps_order_and_stops_after_close():
    bus = tasks.EventBus()
    bus.emit(tasks.EVENT_LOG, "one")
    bus.emit(tasks.EVENT_PROGRESS, "two")

    events = bus.drain()
    assert [(event.kind, event.payload) for event in events] == [
        (tasks.EVENT_LOG, "one"),
        (tasks.EVENT_PROGRESS, "two"),
    ]
    assert bus.drain() == []

    bus.close()
    bus.emit(tasks.EVENT_LOG, "three")
    assert bus.closed is True
    assert bus.drain() == []


def test_event_bus_never_blocks_a_worker_when_full():
    bus = tasks.EventBus(maxsize=2)
    for index in range(10):
        bus.emit(tasks.EVENT_LOG, index)  # must not raise when the UI is slow
    assert len(bus.drain()) == 2


def test_log_handler_forwards_formatted_records():
    bus = tasks.EventBus()
    logger = logging.getLogger("pdf_ai_batch.test.tasks")
    logger.setLevel(logging.INFO)
    logger.handlers = [tasks.QueueLogHandler(bus)]
    logger.propagate = False

    logger.info("Sveiki %s", "pasaule")

    events = bus.drain()
    assert len(events) == 1
    assert events[0].kind == tasks.EVENT_LOG
    assert "Sveiki pasaule" in events[0].payload


def test_task_runner_reports_progress_done_and_busy_state():
    bus = tasks.EventBus()
    runner = tasks.TaskRunner(bus)

    def task(progress):
        for page in (1, 2):
            progress(page)
        return "summary"

    assert runner.start("RUN ALL", task) is True
    assert runner.busy is True
    assert runner.start("second", task) is False  # one task at a time

    runner.join(timeout=5)
    assert runner.busy is False

    events = bus.drain()
    assert [event.kind for event in events] == [
        tasks.EVENT_PROGRESS,
        tasks.EVENT_PROGRESS,
        tasks.EVENT_DONE,
    ]
    assert [event.payload for event in events] == [1, 2, "summary"]


def test_task_runner_reports_an_exception_as_an_error_event():
    bus = tasks.EventBus()
    runner = tasks.TaskRunner(bus)

    def boom(progress):  # pragma: no cover - the exception is the point
        raise RuntimeError("COM nav pieejams")

    runner.start("RUN", boom)
    runner.join(timeout=5)

    events = bus.drain()
    assert len(events) == 1
    assert events[0].kind == tasks.EVENT_ERROR
    assert isinstance(events[0].payload, RuntimeError)
    assert "COM" in str(events[0].payload)
    assert runner.busy is False


def test_task_runner_runs_on_a_real_thread():
    bus = tasks.EventBus()
    runner = tasks.TaskRunner(bus)
    main_thread = __import__("threading").current_thread().name
    seen: list[str] = []

    def task(progress):
        seen.append(__import__("threading").current_thread().name)
        time.sleep(0.05)
        return "done"

    runner.start("RUN", task)
    runner.join(timeout=5)

    assert seen and seen[0] != main_thread