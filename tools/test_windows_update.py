"""Real Windows subprocess + directory transaction tests, using a test stub EXE."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import argparse, tempfile
parser = argparse.ArgumentParser()
parser.add_argument('--result-directory', type=Path)
args = parser.parse_args()
if os.name != 'nt':
    raise SystemExit('This integration test requires Windows')
repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))
from pos import update_worker, deployment
suite = args.result_directory.resolve() if args.result_directory else Path(tempfile.mkdtemp(prefix='sevimli-native-update-')) / 'results'
suite.mkdir(parents=True, exist_ok=False)
stub = suite / 'stub.exe'
compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(stub),
                str(Path(__file__).with_name('native_update_stub.cs'))], check=True, timeout=60)
results = []
for mode, expected in [('ready','updated'),('crash','rolled-back'),
                       ('slow','running-unconfirmed-backup-retained'),('runtime-bad','unchanged')]:
    case = suite / mode
    case.mkdir()
    os.environ['APPDATA'] = str(case / 'Roaming')
    source = case / 'package'
    target = case / 'Local/SevimliKassa'
    state = case / 'Roaming/SevimliKassa/update'
    state.mkdir(parents=True)
    for folder, setting in ((source, mode),(target,'old')):
        (folder / '_internal').mkdir(parents=True)
        shutil.copy2(stub, folder / 'SevimliKassa.exe')
        (folder / 'mode.txt').write_text(setting)
        (folder / '_internal/python312.dll').write_bytes(b'stub fixture, not a runtime')
    (source/'new-only.dll').write_bytes(b'new')
    (target/'old-only.dll').write_bytes(b'old')
    before = deployment.manifest(target)
    report = update_worker.perform(source, target, state, '9.0.0', ready_timeout=1)
    try:
        assert report['status'] == expected, report
        if expected in ('unchanged','rolled-back'):
            assert deployment.manifest(target) == before
        else:
            assert deployment.manifest(Path(report['backup'])) == before
            assert not (target/'old-only.dll').exists()
        lines = (state/'launches.txt').read_text().splitlines() if (state/'launches.txt').exists() else []
        # Restart of the old stub may still be scheduled just after Popen returns.
        import time
        time.sleep(.2)
        lines = (state/'launches.txt').read_text().splitlines()
        assert len(lines) == (2 if mode == 'crash' else 1), lines
        report['native_launches'] = lines
        report['passed'] = True
        results.append(report)
    finally:
        # Only PIDs started by this test's exact target EXE, never image-name kills.
        for key in ('pid','restarted_pid'):
            pid = report.get(key)
            if pid:
                import ctypes
                from ctypes import wintypes
                k = ctypes.WinDLL('kernel32', use_last_error=True)
                k.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
                k.OpenProcess.restype=wintypes.HANDLE
                k.TerminateProcess.argtypes=(wintypes.HANDLE,wintypes.UINT)
                k.CloseHandle.argtypes=(wintypes.HANDLE,)
                k.QueryFullProcessImageNameW.argtypes=(wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD))
                h=k.OpenProcess(0x1001,False,pid)
                if h:
                    try:
                        buf=ctypes.create_unicode_buffer(32768); size=wintypes.DWORD(len(buf))
                        if k.QueryFullProcessImageNameW(h,0,buf,ctypes.byref(size)) and Path(buf.value).resolve() == (target/'SevimliKassa.exe').resolve():
                            k.TerminateProcess(h,0)
                    finally:
                        k.CloseHandle(h)
(suite/'results.json').write_text(json.dumps(results,indent=2))
print(json.dumps({'passed':len(results),'result':str(suite/'results.json')}))
