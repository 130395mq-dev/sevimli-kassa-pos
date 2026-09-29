"""Disconnected, blocked and ambiguous printer replies must not lose sales
or freeze Qt. Every test uses fakes; no real printer or server is contacted.
"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from . import printer
from .print_service import PrintService


class PrintServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.archive = patch.object(printer, 'archive_dir', return_value=Path(self.folder.name))
        self.archive.start()
        self.addCleanup(self.archive.stop)
        self.send = patch.object(printer, 'send_saved_sale').start()
        self.probe = patch.object(printer, 'job_pending', return_value=True).start()
        self.addCleanup(patch.stopall)
        self.service = PrintService(warn_after=.04, poll_ms=10)
        self.addCleanup(self.close_service)
        self.status, self.notices = [], []
        self.service.status_changed.connect(self.status.append)
        self.service.notice.connect(self.notices.append)
        self.send.return_value = printer.PrintJob('fake', 28, 'receipt')

    def close_service(self):
        self.service.close()
        self.service._worker.join(4)  # Test-only; never wait on a driver in the UI.
        self.app.processEvents()

    def pump(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.003)
        self.fail('Timed out waiting for Qt/worker result')

    def test_disconnected_queue_warns_then_clears_without_resubmission(self):
        self.service.submit('SINOV', 'fake')
        self.pump(lambda: any('Kabel' in s for s in self.status))
        self.assertEqual(self.send.call_count, 1)
        self.assertIn('SINOV', next(Path(self.folder.name).glob('*.txt')).read_text('utf-8-sig'))
        self.probe.return_value = False
        self.pump(lambda: not self.service._pending)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.status[-1], '')
        self.assertIn('Qog', self.notices[-1])
        self.assertNotIn('chop etildi', self.notices[-1])

    def test_blocked_driver_does_not_block_gui_and_archives_second_receipt(self):
        release = threading.Event()
        entered = threading.Event()
        def stuck(*args):
            entered.set()
            release.wait(3)
            return printer.PrintJob('fake', 28, 'receipt')
        self.send.side_effect = stuck
        try:
            self.service.submit('FIRST', 'fake')
            self.pump(entered.is_set)
            self.service.submit('SECOND', 'fake')
            ticks = []
            QTimer.singleShot(0, lambda: ticks.append(True))
            self.pump(lambda: ticks and any('Kabel' in s for s in self.status))
            self.assertEqual(len(list(Path(self.folder.name).glob('*.txt'))), 2)
            self.assertEqual(self.send.call_count, 1)
        finally:
            release.set()
        self.pump(lambda: all(t['job'] for t in self.service._pending.values()))

    def test_stuck_queue_probe_keeps_ui_responsive_and_no_extra_probe_threads(self):
        release = threading.Event()
        entered = threading.Event()
        def stuck(_):
            entered.set()
            release.wait(3)
            return False
        self.probe.side_effect = stuck
        try:
            self.service.submit('SINOV', 'fake')
            self.pump(entered.is_set)
            self.pump(lambda: any('Kabel' in s for s in self.status))
            self.assertEqual(self.probe.call_count, 1)
        finally:
            release.set()
        self.pump(lambda: not self.service._pending)

    def test_failed_queue_read_is_not_reported_as_printed(self):
        self.probe.side_effect = OSError('spooler stopped')
        self.service.submit('SINOV', 'fake')
        self.pump(lambda: any('Kabel' in s for s in self.status))
        self.assertTrue(self.service._pending)
        self.assertEqual(self.notices, [])
        self.assertEqual(self.send.call_count, 1)

    def test_ambiguous_submission_is_not_retried(self):
        self.send.side_effect = OSError('failed after accepting job')
        self.service.submit('SINOV', 'fake')
        self.pump(lambda: self.service._uncertain == 1)
        self.assertIn('tasdiqlanmadi', self.status[-1])
        self.assertEqual(self.send.call_count, 1)
        self.probe.assert_not_called()
        self.assertEqual(len(list(Path(self.folder.name).glob('*.txt'))), 1)

    def test_fallback_is_unverified_not_printed(self):
        self.send.return_value = None
        self.service.submit('SINOV', 'fake')
        self.pump(lambda: self.service._uncertain == 1)
        self.assertIn('tasdiqlanmadi', self.status[-1])
        self.assertEqual(self.notices, [])

    def test_archive_failure_is_visible_and_never_submitted(self):
        with patch.object(printer, 'save', side_effect=OSError('disk full')):
            self.service.submit('SINOV', 'fake')
        self.assertIn('Savdo tarixini', self.status[-1])
        self.send.assert_not_called()

    def test_warning_survives_cart_refresh(self):
        from .ui.main_window import MainWindow
        from .demo import DemoBackend
        window = MainWindow(DemoBackend(), animated_bg=False)
        try:
            window.set_printer_status('Printer: kutilmoqda')
            window.refresh()
            self.assertEqual(window.printer_status.text(), 'Printer: kutilmoqda')
            self.assertFalse(window.printer_status.isHidden())
            window.set_printer_status('')
            self.assertTrue(window.printer_status.isHidden())
        finally:
            window.close()


class WindowsQueueTest(unittest.TestCase):
    def test_reused_identifier_does_not_match_another_document(self):
        api = MagicMock()
        api.EnumJobs.return_value = [{'JobId': 28, 'pDocument': 'other'}]
        with patch.object(printer, 'win32print', api):
            self.assertFalse(printer.job_pending(printer.PrintJob('fake', 28, 'ours')))
        api.ClosePrinter.assert_called_once()

    def test_normal_status_can_still_be_pending(self):
        api = MagicMock()
        api.EnumJobs.return_value = [{'JobId': 28, 'pDocument': 'ours', 'Status': 0}]
        with patch.object(printer, 'win32print', api):
            self.assertTrue(printer.job_pending(printer.PrintJob('fake', 28, 'ours')))

    def test_query_failure_propagates_and_handle_closes(self):
        api = MagicMock()
        api.EnumJobs.side_effect = OSError('offline')
        with patch.object(printer, 'win32print', api), self.assertRaises(OSError):
            printer.job_pending(printer.PrintJob('fake', 28, 'ours'))
        api.ClosePrinter.assert_called_once()

    def test_partial_raw_write_is_not_success(self):
        api = MagicMock()
        api.StartDocPrinter.return_value = 28
        api.WritePrinter.return_value = 0
        with patch.object(printer, 'win32print', api), \
             patch.object(printer, 'head_bytes', return_value=b''), \
             patch.object(printer, '_encode', return_value=b'test'), \
             self.assertRaisesRegex(RuntimeError, "to'liq"):
            printer._print_sale_raw('SINOV', 'fake', '80', 48)
        api.EndDocPrinter.assert_called_once()
        api.ClosePrinter.assert_called_once()


if __name__ == '__main__':
    unittest.main()
