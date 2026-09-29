"""File-system and failure tests for installation and rollback; no real POS."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from . import deployment, update_worker, updater


class DeploymentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'APPDATA': str(self.root / 'Roaming')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.source = self.root / 'package'
        self.target = self.root / 'Local' / 'SevimliKassa'
        for directory, version in ((self.source, b'new'), (self.target, b'old')):
            (directory / '_internal').mkdir(parents=True)
            (directory / 'SevimliKassa.exe').write_bytes(version)
            (directory / '_internal/python312.dll').write_bytes(version)
        (self.target / '_internal/obsolete.dll').write_bytes(b'OLD DLL')
        (self.source / '_internal/added.dll').write_bytes(b'NEW DLL')
        self.old = deployment.manifest(self.target)
        self.new = deployment.manifest(self.source)
        self.state = updater.update_dir()

    def test_update_then_rollback_restores_exact_trees(self):
        staged = deployment.stage(self.source, self.target)
        self.assertEqual(deployment.manifest(self.target), self.old)
        backup = deployment.activate(staged, self.target)
        self.assertEqual(deployment.manifest(self.target), self.new)
        self.assertEqual(deployment.manifest(backup), self.old)
        failed = deployment.rollback(self.target, backup)
        self.assertEqual(deployment.manifest(self.target), self.old)
        self.assertEqual(deployment.manifest(failed), self.new)

    def test_disk_full_keeps_original_installation(self):
        with mock.patch.object(deployment.shutil, 'copytree', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                deployment.stage(self.source, self.target)
        self.assertEqual(deployment.manifest(self.target), self.old)

    def test_corrupted_copy_is_never_activated(self):
        original = deployment.shutil.copytree
        def corrupt(src, dst, *args, **kwargs):
            result = original(src, dst, *args, **kwargs)
            if Path(src) == self.source:
                (Path(dst) / 'SevimliKassa.exe').write_bytes(b'corrupt')
            return result
        with mock.patch.object(deployment.shutil, 'copytree', side_effect=corrupt):
            with self.assertRaises(OSError):
                deployment.stage(self.source, self.target)
        self.assertEqual(deployment.manifest(self.target), self.old)

    def test_failed_backup_rename_leaves_target_unchanged(self):
        staged = deployment.stage(self.source, self.target)
        original = Path.rename
        def locked(path, to):
            if path == self.target:
                raise PermissionError('target locked')
            return original(path, to)
        with mock.patch.object(Path, 'rename', locked):
            with self.assertRaises(PermissionError):
                deployment.activate(staged, self.target)
        self.assertEqual(deployment.manifest(self.target), self.old)

    def test_failed_activation_restores_old_directory(self):
        staged = deployment.stage(self.source, self.target)
        original = Path.rename
        def fail_new(path, to):
            if path == staged:
                raise PermissionError('new directory locked')
            return original(path, to)
        with mock.patch.object(Path, 'rename', fail_new):
            with self.assertRaises(PermissionError):
                deployment.activate(staged, self.target)
        self.assertEqual(deployment.manifest(self.target), self.old)

    def test_recovery_failure_preserves_both_versions(self):
        staged = deployment.stage(self.source, self.target)
        backup = deployment.activate(staged, self.target)
        original = Path.rename
        def fail_backup(path, to):
            if path == backup:
                raise PermissionError('restore blocked')
            return original(path, to)
        with mock.patch.object(Path, 'rename', fail_backup):
            with self.assertRaises(PermissionError):
                deployment.rollback(self.target, backup)
        self.assertEqual(deployment.manifest(backup), self.old)
        self.assertEqual(deployment.manifest(self.target), self.new)

    def test_refuse_nested_copy_and_unrelated_rollback(self):
        with self.assertRaises(ValueError):
            deployment.stage(self.source, self.source / 'nested')
        with self.assertRaises(ValueError):
            deployment.rollback(self.target, self.source)
        self.assertEqual(deployment.manifest(self.target), self.old)

    def _perform(self, first, *, ready=False, runtime_error=None):
        self.runtime = mock.Mock(side_effect=runtime_error)
        self.launch = mock.Mock(side_effect=[first, mock.Mock(pid=222)])
        with mock.patch.object(update_worker, 'runtime_check', self.runtime), \
             mock.patch.object(update_worker, 'start_register', self.launch), \
             mock.patch.object(update_worker, 'await_ready', return_value=ready), \
             mock.patch.object(deployment, 'register_closed'):
            return update_worker.perform(self.source, self.target, self.state, '9.0.0')

    def test_runtime_failure_restarts_old_without_replacing_files(self):
        result = self._perform(mock.Mock(pid=111), runtime_error=RuntimeError('bad DLL'))
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(deployment.manifest(self.target), self.old)
        self.assertEqual(self.launch.call_count, 1)

    def test_new_process_crash_rolls_back_without_new_dll_leftovers(self):
        result = self._perform(mock.Mock(pid=111, poll=mock.Mock(return_value=1)))
        self.assertEqual(result['status'], 'rolled-back')
        self.assertEqual(deployment.manifest(self.target), self.old)
        self.assertEqual(self.launch.call_count, 2)

    def test_unconfirmed_live_process_not_killed_or_launched_twice(self):
        process = mock.Mock(pid=111, poll=mock.Mock(return_value=None))
        result = self._perform(process)
        self.assertEqual(result['status'], 'running-unconfirmed-backup-retained')
        self.assertEqual(deployment.manifest(Path(result['backup'])), self.old)
        self.assertEqual(self.launch.call_count, 1)
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_success_keeps_recovery_copy(self):
        result = self._perform(mock.Mock(pid=111), ready=True)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(deployment.manifest(self.target), self.new)
        self.assertEqual(deployment.manifest(Path(result['backup'])), self.old)

    def test_health_requires_version_nonce_and_exact_child_pid(self):
        ready = self.state / 'run-ready.json'
        process = mock.Mock(pid=111, poll=mock.Mock(return_value=None))
        for data in ({'pid': 999, 'version': '9.0.0', 'nonce': 'correct'},
                     {'pid': 111, 'version': '8.0.0', 'nonce': 'correct'},
                     {'pid': 111, 'version': '9.0.0', 'nonce': 'old'}):
            ready.write_text(json.dumps(data))
            self.assertFalse(update_worker.await_ready(process, ready, '9.0.0', 'correct', .01))
        ready.write_text(json.dumps({'pid':111, 'version':'9.0.0', 'nonce':'correct'}))
        self.assertTrue(update_worker.await_ready(process, ready, '9.0.0', 'correct', .01))

    def test_extract_rejects_escape_and_version_traversal(self):
        archive = self.root / 'bad.zip'
        for name in ('../outside', 'C:/outside', 'a\\outside', '/outside'):
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr(name, 'no')
            self.assertIsNone(updater._extract(archive, '9.0.0'))
        with self.assertRaises(ValueError):
            updater.staged_path('../outside')
        self.assertIsNone(updater._extract(archive, '../outside'))

    def test_repeated_extract_keeps_previous_package(self):
        archive = self.root / 'valid.zip'
        with zipfile.ZipFile(archive, 'w') as out:
            for f in self.source.rglob('*'):
                if f.is_file(): out.write(f, 'SevimliKassa/' + f.relative_to(self.source).as_posix())
        first = updater._extract(archive, '9.0.0')
        second = updater._extract(archive, '9.0.0')
        self.assertNotEqual(first, second)
        self.assertEqual(deployment.manifest(first), deployment.manifest(second))

    def test_readiness_marker_identifies_current_process(self):
        with mock.patch.dict(os.environ, {'SEVIMLI_UPDATE_NONCE': 'trial'}):
            updater.mark_started()
        value = json.loads((self.state / 'run-ready.json').read_text())
        self.assertEqual(value['pid'], os.getpid())
        self.assertEqual(value['nonce'], 'trial')

    @unittest.skipUnless(os.name == 'nt', 'Windows mutex')
    def test_open_register_blocks_install_without_killing_it(self):
        with deployment.register_closed():
            with self.assertRaises(RuntimeError):
                with deployment.register_closed():
                    self.fail('second installation got the lock')
        # Handle is closed on failure; a new installation can acquire it.
        with deployment.register_closed():
            pass


if __name__ == '__main__':
    unittest.main()
