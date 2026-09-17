"""
«Bir login — bir kompyuter» va «Chiqish»gacha eslab qolish — kassa tomoni.

    QT_QPA_PLATFORM=offscreen python -m unittest pos.test_session
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DeviceIdTest(unittest.TestCase):
    def setUp(self):
        from . import device

        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"APPDATA": self.tmp.name})
        self.env.start()
        device._cached.clear()

    def tearDown(self):
        from . import device

        device._cached.clear()
        self.env.stop()
        self.tmp.cleanup()

    def test_belgi_yaratiladi_va_saqlanadi(self):
        from . import device

        first = device.device_id()
        self.assertGreaterEqual(len(first), 32)
        device._cached.clear()
        self.assertEqual(device.device_id(), first)  # fayldan qayta o'qildi
        path = os.path.join(self.tmp.name, "SevimliKassa", "device.txt")
        self.assertTrue(os.path.exists(path))

    def test_nomi_ascii(self):
        from . import device

        with mock.patch("platform.node", return_value="Kassa-Ümid-7"):
            self.assertEqual(device.device_name(), "Kassa-mid-7")


class _Resp:
    def __init__(self, payload: dict):
        self.raw = json.dumps(payload).encode()

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int, error: str):
    return urllib.error.HTTPError(
        "http://x", code, "x", {}, io.BytesIO(json.dumps({"error": error}).encode())
    )


class HubHeadersTest(unittest.TestCase):
    def hub(self):
        from .config import Config
        from .hub import Hub

        return Hub(Config(server_url="http://srv", token="tok"))

    def test_har_sorovda_qurilma_sarlavhasi(self):
        seen = {}

        def fake_open(request, timeout=0):
            seen["headers"] = dict(request.header_items())
            return _Resp({"ok": True})

        with mock.patch("urllib.request.urlopen", fake_open):
            self.hub().hello()
        h = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertIn("x-device", h)
        self.assertGreaterEqual(len(h["x-device"]), 32)
        self.assertIn("x-device-name", h)
        self.assertEqual(h["x-kassa-version"], __import__("pos.version", fromlist=["VERSION"]).VERSION)

    def test_409_kirishda_busy_xatosi(self):
        from .hub import HubBusyError

        with mock.patch("urllib.request.urlopen",
                        side_effect=_http_error(409, "Bu login hozir «Kassa-1 · PC» kompyuterida ishlayapti")):
            with self.assertRaises(HubBusyError) as cm:
                self.hub().login("kassa1", "1111")
        self.assertIn("Kassa-1 · PC", str(cm.exception))

    def test_409_davom_etishda_ham(self):
        from .hub import HubBusyError

        with mock.patch("urllib.request.urlopen", side_effect=_http_error(409, "band")):
            with self.assertRaises(HubBusyError):
                self.hub().resume_session(0)

    def test_409_boshqa_yolda_oddiy_xato(self):
        from .hub import HubBusyError, HubError

        with mock.patch("urllib.request.urlopen", side_effect=_http_error(409, "ombor tanlanmagan")):
            with self.assertRaises(HubError) as cm:
                self.hub().open_shift(0, 0)
        self.assertNotIsInstance(cm.exception, HubBusyError)

    def test_resume_sessiya_tokenini_eslab_qoladi(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_Resp({"cashier": {"id": 0}, "session": "abc.def"})):
            h = self.hub()
            h.resume_session(0)
        self.assertEqual(h.session, "abc.def")

    def test_logout_sessiyani_tozalaydi(self):
        with mock.patch("urllib.request.urlopen", return_value=_Resp({"ok": True, "released": 1})):
            h = self.hub()
            h.session = "abc.def"
            self.assertEqual(h.logout()["released"], 1)
        self.assertEqual(h.session, "")


class LoginScreenResumeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication, QWidget

        cls.app = QApplication.instance() or QApplication([])
        cls.parent = QWidget()
        cls.parent.resize(1000, 700)

    def screen(self):
        from .ui.login_screen import LoginScreen

        return LoginScreen(self.parent, "Chilonzor", "Kassa-1")

    def test_davom_etish_rejimi(self):
        s = self.screen()
        s.open_resume("Nilufar")
        self.assertTrue(s.resume_mode)
        self.assertTrue(s.card.isHidden())
        self.assertIn("Nilufar", s.resume_who.text())
        # Oddiy kirish ekraniga qaytish
        s.open()
        self.assertFalse(s.resume_mode)
        self.assertFalse(s.card.isHidden())

    def test_tugmalar_signal_beradi(self):
        s = self.screen()
        got = []
        s.resume_requested.connect(lambda: got.append("resume"))
        s.logout_requested.connect(lambda: got.append("logout"))
        s.open_resume("N")
        s.resume_btn.click()
        # «Chiqish» endi tasdiq so'raydi — adashib bosilsa chiqmaydi.
        s._ask_logout = lambda: False
        s.resume_logout.click()
        self.assertEqual(got, ["resume"])  # tasdiqsiz chiqmadi
        s._ask_logout = lambda: True
        s.resume_logout.click()
        self.assertEqual(got, ["resume", "logout"])  # tasdiqdan keyin chiqdi

    def test_xato_xabari_kirish_ekranida(self):
        s = self.screen()
        s.open()
        s.show_error("Bu login hozir «Kassa-1 · PC» kompyuterida ishlayapti")
        self.assertIn("Kassa-1", s.hint.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)


class LoginScreenKeyboardTest(unittest.TestCase):
    """Ekran klaviaturasi standart YASHIRIN; «⌨» tugmasi ko'rsatadi/yashiradi,
    tanlov signal orqali kassaga eslab qolinadi; jismoniy klaviatura ishlaydi."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtWidgets import QWidget
        self.parent = QWidget()
        self.parent.resize(1200, 760)

    def _screen(self, **kw):
        from pos.ui.login_screen import LoginScreen
        return LoginScreen(self.parent, "Chilonzor", "Kassa-1", **kw)

    def test_standart_yashirin_va_tugma_bilan_chiqadi(self):
        s = self._screen()
        self.assertFalse(s.keyboard_visible)
        self.assertTrue(s.keyboard.isHidden())
        got = []
        s.keyboard_toggled.connect(got.append)
        s.kb_toggle.click()
        self.assertTrue(s.keyboard_visible)
        self.assertEqual(got, [True])
        s.kb_toggle.click()
        self.assertFalse(s.keyboard_visible)
        self.assertEqual(got, [True, False])

    def test_eslab_qolingan_tanlov_bilan_ochiladi(self):
        s = self._screen(show_keyboard=True)
        self.assertTrue(s.keyboard_visible)
        self.assertFalse(s.keyboard.isHidden())

    def test_jismoniy_klaviatura_ishlaydi(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        s = self._screen()
        for ch in "ab":
            s.keyPressEvent(QKeyEvent(QEvent.KeyPress, ord(ch.upper()), Qt.NoModifier, ch))
        self.assertEqual(s.values["login"], "ab")
        s.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier, "\t"))
        s.keyPressEvent(QKeyEvent(QEvent.KeyPress, ord("1"), Qt.NoModifier, "1"))
        self.assertEqual(s.values["parol"], "1")
