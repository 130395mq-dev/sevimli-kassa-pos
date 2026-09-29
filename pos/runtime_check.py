"""Opt-in frozen-runtime smoke check. Never install, print or contact a server."""
import json
import os
import sys
import traceback
from pathlib import Path


def run(destination):
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)  # Never reuse a real POS data folder.
    os.environ.update(APPDATA=str(root / 'AppData'), LOCALAPPDATA=str(root / 'Local'),
                      QT_QPA_PLATFORM='offscreen')
    if os.name == 'nt':
        os.environ['QT_QPA_FONTDIR'] = str(Path(os.environ['SystemRoot']) / 'Fonts')
    def no_network(event, args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            raise RuntimeError('Runtime check: network disabled')
    sys.addaudithook(no_network)
    result = {'frozen': bool(getattr(sys, 'frozen', False)), 'ok': False}
    try:
        from PySide6 import __version__ as qt_version
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont, QFontDatabase
        from . import main, printer  # Imports only; do not call main().
        from .demo import DemoBackend
        from .ui.main_window import MainWindow
        from .print_service import PrintService
        from .store import Store
        app = QApplication.instance() or QApplication([])
        if os.name == 'nt':
            font = Path(os.environ['SystemRoot']) / 'Fonts/segoeui.ttf'
            assert QFontDatabase.addApplicationFont(str(font)) >= 0
            app.setFont(QFont('Segoe UI', 10))
            assert printer._HAS_WIN32, 'win32print missing from Windows package'
        window = MainWindow(DemoBackend(), animated_bg=False)
        window.resize(1024, 768)
        window.show()
        app.processEvents()
        window.set_printer_status('SINOV: printer navbati')
        app.processEvents()
        assert window.grab().save(str(root / 'window.png'))
        window.close()
        # Frozen SQLite and migration path, with a fresh synthetic database.
        db = root / 'check.db'
        store = Store(db)
        store.set('runtime-check', 'saved')
        store.close()
        store = Store(db)
        assert store.get('runtime-check') == 'saved'
        store.close()
        import sqlite3
        with sqlite3.connect(db) as con:
            result['integrity'] = con.execute('pragma integrity_check').fetchone()[0]
        assert result['integrity'] == 'ok'
        result.update(ok=True, qt=qt_version, printer_api=printer._HAS_WIN32,
                      python=sys.version, ui='1024x768 offscreen',
                      scope='runtime/import/UI/SQLite only; no install/update/physical print')
    except Exception:
        result['error'] = traceback.format_exc()
    (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
