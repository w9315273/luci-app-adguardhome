"""隔离更新器的文件和下载命令, 验证并发与失败后的锁释放."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpdateLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='agh-lock-test-')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.processes = []
        self.addCleanup(self.stop_processes)
        self.env = dict(os.environ, TEST_DIR=str(self.directory))
        self.write_executable('uci', '''#!/bin/sh
case "$2" in
*.binpath) echo "$TEST_DIR/core";;
*.enabled) echo 0;;
esac
''')
        self.write_executable('core', '#!/bin/sh\necho "AdGuardHome version v1.2.3"\n')
        self.write_executable('uclient-fetch', '''#!/bin/sh
touch "$TEST_DIR/ready"
while [ ! -f "$TEST_DIR/release" ]; do sleep 0.02; done
printf '%s\n' '{"tag_name":"v1.2.3"}'
''')
        source = (ROOT / 'root/usr/share/AdGuardHome/update_core.sh').read_text()
        source = source.replace('PATH="/usr/sbin:/usr/bin:/sbin:/bin"',
                                'PATH="$TEST_DIR:/usr/bin:/bin"')
        for path in ['/var/lock/AdGuardHome-update.lock', '/var/run/update_core_error',
                     '/var/run/update_core', '/tmp/AdGuardHome_update.log']:
            source = source.replace(path, str(self.directory / Path(path).name))
        self.script = self.write_executable('updater', source)

    def write_executable(self, name, content):
        path = self.directory / name
        path.write_text(content)
        path.chmod(0o755)
        return path

    def start(self, *args):
        proc = subprocess.Popen(['sh', str(self.script), *args], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        self.processes.append(proc)
        return proc

    def stop_processes(self):
        for proc in self.processes:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=5)

    def wait_ready(self):
        deadline = time.monotonic() + 5
        while not (self.directory / 'ready').exists():
            self.assertLess(time.monotonic(), deadline, 'updater did not reach downloader')
            time.sleep(0.01)

    def test_normal_and_force_contenders_preserve_owner_state(self):
        owner = self.start()
        self.wait_ready()
        log = self.directory / 'AdGuardHome_update.log'
        before = log.read_bytes()
        for args in [(), ('force',)]:
            contender = self.start(*args)
            contender.communicate(timeout=5)
            self.assertEqual(contender.returncode, 2)
            self.assertIsNone(owner.poll())
            self.assertEqual(log.read_bytes(), before)
            self.assertTrue((self.directory / 'update_core').exists())
            self.assertFalse((self.directory / 'update_core_error').exists())
        (self.directory / 'release').touch()
        owner.communicate(timeout=5)
        self.assertEqual(owner.returncode, 0)
        self.assertFalse((self.directory / 'update_core').exists())
        self.assertTrue((self.directory / 'AdGuardHome-update.lock').exists())

    def test_killed_owner_does_not_leave_lock_held(self):
        owner = self.start()
        self.wait_ready()
        os.killpg(owner.pid, signal.SIGKILL)
        owner.communicate(timeout=5)
        (self.directory / 'release').touch()
        successor = self.start()
        successor.communicate(timeout=5)
        self.assertEqual(successor.returncode, 0)
        self.assertFalse((self.directory / 'update_core').exists())

    def test_failure_sets_error_and_releases_lock(self):
        self.write_executable('uclient-fetch', '#!/bin/sh\nexit 1\n')
        for _ in range(2):
            proc = self.start()
            proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 1)
            self.assertTrue((self.directory / 'update_core_error').exists())
            self.assertFalse((self.directory / 'update_core').exists())


if __name__ == '__main__':
    unittest.main()
