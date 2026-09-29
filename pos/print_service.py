"""Non-blocking receipt submission and conservative Windows queue monitoring.

Only this session's jobs are observed. No automatic retry or queue deletion:
an uncertain Windows reply may already have produced a physical receipt.
Sales/history remain the source for recovery after an application restart.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from . import printer
from .i18n import tr

logger = logging.getLogger(__name__)


def _emit(signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:
        pass  # Application has closed; receipt archive and sale still exist.


def _send_loop(work, result):
    while True:
        task = work.get()
        if task is None:
            return
        key, args = task
        try:
            job = printer.send_saved_sale(*args)
            _emit(result, key, job, "")
        except Exception:
            logger.exception("Printer submission uncertain; archive=%s", key)
            _emit(result, key, None, "unknown")


def _probe_jobs(jobs, result):
    states = {}
    for key, job in jobs:
        try:
            states[key] = printer.job_pending(job)
        except Exception:
            logger.debug("Printer queue could not be read: %s", key)
            states[key] = None
    _emit(result, states)


class PrintService(QObject):
    status_changed = Signal(str)
    notice = Signal(str)
    _submitted = Signal(str, object, str)
    _probed = Signal(object)

    def __init__(self, parent=None, *, warn_after=10.0, poll_ms=1000):
        super().__init__(parent)
        self._pending = {}
        self._uncertain = 0
        self._last_problem = ""
        self._probing = False
        self._closed = False
        self._warn_after = warn_after
        self._work = queue.Queue()
        self._submitted.connect(self._on_submitted)
        self._probed.connect(self._on_probed)
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._worker = threading.Thread(target=_send_loop, args=(self._work, self._submitted),
                                        name="sevimli-print", daemon=True)
        self._worker.start()

    def submit(self, text, printer_name="", paper="80", width=48, name="chek"):
        if self._closed:
            raise RuntimeError("Chop etish xizmati yopilgan")
        # Archive before scheduling work so a slow or broken driver cannot
        # lose the receipt text. The sale itself is already durable in SQLite.
        try:
            plain = text + "\n" + "\n".join(t.center(width)[:width]
                                             for t in printer.THANK_YOU) + "\n"
            path = printer.save(plain, name)
        except Exception:
            logger.exception("Receipt archive failed; sale is in history")
            self._uncertain += 1
            self._last_problem = tr("Chek fayli saqlanmadi. Savdo tarixini tekshiring.")
            self._show_status()
            return self._last_problem
        key = str(path)
        self._pending[key] = {"since": time.monotonic(), "job": None, "warned": False}
        self._work.put((key, (text, path, printer_name, paper, width)))
        self._show_status()
        return tr("Chek chop etish uchun navbatga olindi. Qog'oz chiqishini tekshiring.")

    @Slot(str, object, str)
    def _on_submitted(self, key, job, error):
        if key not in self._pending:
            return
        if error or job is None:
            self._pending.pop(key)
            self._uncertain += 1
            self._last_problem = tr(
                "Chop etish tasdiqlanmadi. Printerni va Windows navbatini tekshiring; "
                "takror bosishga shoshilmang. Chek fayli: {p}"
            ).format(p=Path(key).name)
        else:
            self._pending[key]["job"] = job
        self._show_status()

    @Slot(object)
    def _on_probed(self, states):
        self._probing = False
        for key, pending in states.items():
            task = self._pending.get(key)
            if task is not None and pending is False:
                self._pending.pop(key)
                # Removal can mean printing OR cancellation. Never say printed.
                self.notice.emit(tr("Chek Windows navbatidan chiqdi. Qog'ozni tekshiring."))
        self._show_status()

    def _show_status(self):
        delayed = 0
        for task in self._pending.values():
            if time.monotonic() - task["since"] >= self._warn_after:
                task["warned"] = True
                delayed += 1
        parts = []
        if self._pending:
            if delayed:
                parts.append(tr(
                    "Printer: {n} ta chek kutilmoqda. Kabel va qog'ozni tekshiring. "
                    "Qayta chop etmang — navbatdagi chek ulanish tiklanganda chiqishi mumkin."
                ).format(n=len(self._pending)))
            else:
                parts.append(tr("Printer: {n} ta chek navbatda.").format(n=len(self._pending)))
        if self._uncertain:
            parts.append(tr("Tekshirish kerak: {n} ta. ").format(n=self._uncertain)
                         + self._last_problem)
        self.status_changed.emit("\n".join(parts))

    def _tick(self):
        self._show_status()  # Still runs if Windows submission/probe is blocked.
        jobs = [(key, task['job']) for key, task in self._pending.items() if task['job']]
        if jobs and not self._probing:
            self._probing = True
            threading.Thread(target=_probe_jobs, args=(jobs, self._probed),
                             name="sevimli-print-status", daemon=True).start()

    def close(self):
        self._closed = True
        self._timer.stop()
        # Never join a driver thread on the GUI thread. Work already queued
        # may finish while the process exits; never auto-replay it on restart.
        self._work.put(None)
