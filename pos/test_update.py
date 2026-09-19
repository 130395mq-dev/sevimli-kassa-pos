"""Ilova yangilanishi: versiya solishtirish va yuklab olish."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from . import updater
from .config import Config
from .hub import Hub, HubError
from .version import is_newer, version_key

BODY = b"MZ" + b"\x00" * 1_200_000


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer tok":
            self.send_response(401); self.end_headers(); return
        if self.path.startswith("/api/v1/update/download"):
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)
        elif self.path == "/api/v1/version":
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"version":"9.0.0","url":"x","mandatory":true}')
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):  # jim
        pass


class VersionTest(unittest.TestCase):
    def test_raqam_boyicha(self):
        self.assertTrue(is_newer("1.10.0", "1.9.0"))
        self.assertFalse(is_newer("1.1.0", "1.1.0"))
        self.assertFalse(is_newer("", "1.1.0"))
        self.assertEqual(version_key("v2.1"), (2, 1, 0))


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        port = self.srv.server_address[1]
        self.hub = Hub(Config(server_url=f"http://127.0.0.1:{port}", token="tok"))
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.srv.shutdown()
        self.dir.cleanup()

    def test_versiya_soraladi_va_sarlavha_ketadi(self):
        self.assertEqual(self.hub.check_version()["version"], "9.0.0")

    def test_notogri_token_alohida_xato(self):
        from .hub import HubAuthError

        bad = Hub(Config(server_url=self.hub.config.base, token="yolgon"))
        with self.assertRaises(HubAuthError):
            bad.hello()
        # connect (login-parol) 401 — oddiy HubError (oynada ko'rsatiladi)
        with self.assertRaises(HubError) as cm:
            bad.connect("a", "b")
        self.assertNotIsInstance(cm.exception, HubAuthError)

    def test_yuklab_olish_va_tekshirish(self):
        dest = Path(self.dir.name) / "SevimliKassa-9.0.0.exe"
        seen = []
        self.hub.download(
            f"{self.hub.config.base}/api/v1/update/download?v=9.0.0", dest,
            progress=lambda d, t: seen.append((d, t)),
            expected_sha256=hashlib.sha256(BODY).hexdigest(),
        )
        self.assertTrue(dest.exists())
        self.assertEqual(dest.stat().st_size, len(BODY))
        self.assertFalse(dest.with_suffix(".exe.part").exists())
        self.assertEqual(seen[-1], (len(BODY), len(BODY)))

    def test_buzuq_fayl_qabul_qilinmaydi(self):
        dest = Path(self.dir.name) / "x.exe"
        with self.assertRaises(HubError):
            self.hub.download(
                f"{self.hub.config.base}/api/v1/update/download?v=9.0.0", dest,
                expected_sha256="00" * 32,
            )
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".exe.part").exists())


class ApplyTest(unittest.TestCase):
    def test_yigilmagan_muhitda_hech_narsa_qilmaydi(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "new.exe"
            f.write_bytes(b"MZ")
            self.assertFalse(updater.apply(f))
            self.assertFalse(updater.apply(Path(d) / "yoq.exe"))

    def test_bat_papkani_robocopy_bilan_kochiradi(self):
        """Ko'chirish skripti butun papkani robocopy bilan ishonchli
        ko'chirishi + zaxira/rollback qilishi kerak."""
        bat = updater._BAT.format(
            new="N", target="T", exe="T\\SevimliKassa.exe",
            backup="B", flag="F",
        )
        self.assertIn("robocopy", bat)
        # robocopy chiqish kodi 8+ bo'lsa qayta urinadi (exe qulflangan)
        self.assertIn("GEQ 8", bat)
        # Ochishdan oldin kutadi (disk yozuvi tugasin)
        self.assertIn("timeout /t 2", bat)
        # Zaxira olinadi (TARGET -> BACKUP) va rollback yo'li bor (BACKUP -> TARGET)
        self.assertIn('robocopy "%TARGET%" "%BACKUP%"', bat)
        self.assertIn('robocopy "%BACKUP%" "%TARGET%"', bat)
        # Sog'liq bayrog'i kutiladi (rollback qaroriga asos)
        self.assertIn('exist "%FLAG%"', bat)

    def test_mark_started_bayroq_yozadi(self):
        """mark_started() sog'liq bayrog'ini yozadi (versiya bilan)."""
        updater.run_flag().unlink(missing_ok=True)
        updater.mark_started()
        self.assertTrue(updater.run_flag().exists())
        from pos.version import VERSION
        self.assertEqual(updater.run_flag().read_text(encoding="utf-8"), VERSION)
        updater.run_flag().unlink(missing_ok=True)

    def test_extract_toliq_papkani_qaytaradi(self):
        """ZIP ichida SevimliKassa.exe va python312.dll bo'lsa — o'sha
        papka qaytariladi."""
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            zp = Path(d) / "SevimliKassa-9.9.9.zip"
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("SevimliKassa/SevimliKassa.exe", b"MZ")
                z.writestr("SevimliKassa/_internal/python312.dll", b"x" * 100)
            root = updater._extract(zp, "9.9.9")
            self.assertIsNotNone(root)
            self.assertTrue((root / "SevimliKassa.exe").exists())
            import shutil
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_extract_chala_zip_rad_etiladi(self):
        """python312.dll yo'q ZIP o'rnatilmaydi (None qaytadi)."""
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            zp = Path(d) / "SevimliKassa-9.9.8.zip"
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("SevimliKassa/SevimliKassa.exe", b"MZ")
                # _internal/python312.dll ATAYLAB yo'q
            self.assertIsNone(updater._extract(zp, "9.9.8"))


if __name__ == "__main__":
    unittest.main()


class InstallerTest(unittest.TestCase):
    def test_yigilmagan_muhitda_ornatmaydi(self):
        from . import installer

        self.assertFalse(installer.is_frozen())
        self.assertFalse(installer.ensure_installed())

    def test_server_manzili_ichida(self):
        from .config import DEFAULT_SERVER, Config

        self.assertTrue(DEFAULT_SERVER.startswith("https://"))
        self.assertEqual(Config().base, DEFAULT_SERVER.rstrip("/"))
        self.assertFalse(Config().is_ready)          # token yo'q
        self.assertTrue(Config(token="x").is_ready)  # faqat token yetarli


class UpdateScriptSafetyTest(unittest.TestCase):
    """Yangilash skripti ikkinchi nusxani ochib yubormasin.

    2026-09-19: skript yangi versiya ishga tushganini 20 soniya kutardi.
    Sekin monoblokda (yoki antivirus yangi 50 MB faylni tekshirayotganda)
    bu yetmasdi — skript «yiqildi» deb zaxiradan tiklab, yana bitta nusxa
    ochardi. Natijada kassada 2-3 nusxa ishlab turardi.
    """

    def script(self) -> str:
        from . import updater

        return updater._BAT

    def test_kutish_vaqti_uzaytirilgan(self):
        self.assertIn("if %m% lss 90 goto health", self.script())
        self.assertNotIn("if %m% lss 20 goto health", self.script())

    def test_dastur_ishlab_tursa_rollback_qilmaydi(self):
        bat = self.script()
        self.assertIn("tasklist", bat)
        guard = bat.index("tasklist")
        rollback = bat.index('robocopy "%BACKUP%"')
        # Tekshiruv rollbackdan OLDIN turishi shart
        self.assertLess(guard, rollback)

    def test_rollback_faqat_bir_marta_ochadi(self):
        # «start» ikki joyda: muvaffaqiyatli yangilanishdan keyin va
        # rollbackdan keyin. Uchinchisi bo'lsa — xato.
        self.assertEqual(self.script().count('start "" "%EXE%"'), 2)


class SingleInstanceTest(unittest.TestCase):
    """Bitta kompyuterda bitta nusxa."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"APPDATA": self.tmp.name})
        self.env.start()

    def tearDown(self):
        from . import single

        single.release()
        self.env.stop()
        self.tmp.cleanup()

    def test_birinchi_nusxa_qulfni_oladi(self):
        from . import single

        self.assertTrue(single.acquire("sinov-kassa"))

    def test_ikkinchi_jarayon_qulfni_ololmaydi(self):
        import subprocess
        import sys
        from pathlib import Path

        from . import single

        self.assertTrue(single.acquire("sinov-kassa"))
        root = str(Path(__file__).resolve().parent.parent)
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from pos import single;"
            "print('OK' if single.acquire('sinov-kassa') else 'BAND')" % root
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            env={**os.environ, "APPDATA": self.tmp.name},
        )
        self.assertEqual(out.stdout.strip(), "BAND", out.stderr)

    def test_boshatilsa_qayta_olinadi(self):
        from . import single

        self.assertTrue(single.acquire("sinov-kassa"))
        single.release()
        self.assertTrue(single.acquire("sinov-kassa"))

    def test_xato_bolsa_dastur_toxtamaydi(self):
        """Qulf ishlamasa ham kassa ochilishi kerak."""
        from . import single

        with mock.patch.object(single, "_acquire_posix", side_effect=OSError("yo'q")):
            with mock.patch.object(single, "_acquire_windows", side_effect=OSError("yo'q")):
                self.assertTrue(single.acquire("sinov-kassa"))

    def test_oynani_chiqarish_windowssiz_xato_bermaydi(self):
        from . import single

        self.assertFalse(single.raise_existing_window())

