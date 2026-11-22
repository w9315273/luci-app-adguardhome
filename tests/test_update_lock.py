"""隔离更新器的文件和下载命令, 验证并发与失败后的锁释放."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
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
*.enabled) echo "${ENABLED:-0}";;
esac
''')
        self.write_executable('core', '#!/bin/sh\necho "AdGuardHome version v1.2.3"\n')
        self.write_executable('uclient-fetch', '''#!/bin/sh
while [ "$#" -gt 1 ]; do
    case "$1" in
        -q) shift ;;
        -T) shift 2 ;;
        -O) output=$2; shift 2 ;;
        --header=*) header=${1#--header=}; shift ;;
        --header) header=$2; shift 2 ;;
        *) exit 2 ;;
    esac
done
touch "$TEST_DIR/ready"
while [ ! -f "$TEST_DIR/release" ]; do sleep 0.02; done
case "$1" in
    */latest) exec cp "$TEST_DIR/release.json" "$output" ;;
esac
echo "$1" >> "$TEST_DIR/requests"
case "$1" in
    https://api.github.com/repos/AdguardTeam/AdGuardHome/releases/assets/123)
        [ "$header" = 'Accept: application/octet-stream' ] || exit 2
        if [ "$FAIL_API" = 1 ]; then echo partial > "$output"; exit 4; fi ;;
    https://test/core)
        if [ "$FAIL_DIRECT" = 1 ]; then
            echo 'Connection error: Connection timed out' >&2
            exit 4
        fi ;;
    *) exit 2 ;;
esac
cp "$TEST_DIR/core.tar.gz" "$output"
''')
        self.write_executable('apk', '#!/bin/sh\necho "${ARCH:-x86_64}"\n')
        self.write_executable('jsonfilter', '''#!/usr/bin/env python3
import json, sys
if '-i' in sys.argv:
    data = json.load(open(sys.argv[2]))
    expr = sys.argv[-1]
    if expr == '@.tag_name':
        print(data['tag_name'])
    else:
        for asset in data['assets']:
            if '"' + asset['name'] + '"' in expr and expr.split('.')[-1] in asset:
                print(asset[expr.split('.')[-1]])
''')
        self.set_release('v1.2.3')
        self.state = self.directory / 'AdGuardHome-update.state'
        self.log = self.directory / 'AdGuardHome_update.log'
        source = (ROOT / 'root/usr/share/AdGuardHome/update_core.sh').read_text()
        source = source.replace('PATH="/usr/sbin:/usr/bin:/sbin:/bin"',
                                'PATH="$TEST_DIR:/usr/bin:/bin"')
        for path in ['/var/lock/AdGuardHome-update.lock', '/var/run/AdGuardHome-update.state',
                     '/tmp/AdGuardHome_update.log', '/tmp/AdGuardHome-update.XXXXXX']:
            source = source.replace(path, str(self.directory / Path(path).name))
        source = source.replace('/etc/init.d/AdGuardHome restart', '"$TEST_DIR/service" restart')
        self.script = self.write_executable('updater', source)

    def set_release(self, version, **asset):
        asset = dict(name='AdGuardHome_linux_amd64.tar.gz', browser_download_url='https://test/core', **asset)
        (self.directory / 'release.json').write_text(json.dumps({'tag_name': version, 'assets': [asset]}))

    def make_archive(self, version):
        candidate = self.write_executable('candidate', f'#!/bin/sh\necho "AdGuardHome version {version}"\n')
        with tarfile.open(self.directory / 'core.tar.gz', 'w:gz') as archive:
            archive.add(candidate, arcname='./AdGuardHome/AdGuardHome')

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
        before = self.log.read_bytes()
        for args in [(), ('force',)]:
            contender = self.start(*args)
            contender.communicate(timeout=5)
            self.assertEqual(contender.returncode, 2)
            self.assertIsNone(owner.poll())
            self.assertEqual(self.log.read_bytes(), before)
            self.assertEqual(self.state.read_text().strip(), 'running')
        (self.directory / 'release').touch()
        owner.communicate(timeout=5)
        self.assertEqual(owner.returncode, 0)
        self.assertEqual(self.state.read_text().strip(), 'current')
        log = self.log.read_text().splitlines()
        self.assertIn('Checking for core updates...', log)
        self.assertIn('The core is already up to date.', log)
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
        self.assertEqual(self.state.read_text().strip(), 'current')

    def test_failure_sets_error_and_releases_lock(self):
        self.write_executable('uclient-fetch', '#!/bin/sh\nexit 1\n')
        for _ in range(2):
            proc = self.start()
            proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(self.state.read_text().strip(), 'failure')

    def test_background_dispatch_replaces_previous_result_before_returning(self):
        self.state.write_text('finished')
        launcher = self.start('--background')
        launcher.communicate(timeout=3)
        self.assertEqual(launcher.returncode, 0)
        self.assertEqual(self.state.read_text().strip(), 'running')
        (self.directory / 'release').touch()
        deadline = time.monotonic() + 5
        while self.state.read_text().strip() != 'current':
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertIn('The core is already up to date.', self.log.read_text().splitlines())

    def test_force_validation_and_service_results(self):
        (self.directory / 'release').touch()
        service = self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/restarted"\nexit 1\n')
        old = (self.directory / 'core').read_bytes()
        self.make_archive('v1.2.3-beta.1')
        for version, digest, message in [
            ('v1.2.3', '', 'The new core could not run or reported an unexpected version.'),
            ('v1.2.3-beta.1', 'sha256:bad', 'Core archive checksum verification failed.'),
        ]:
            self.set_release(version, digest=digest)
            proc = self.start('force')
            proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(self.state.read_text().strip(), 'failure')
            self.assertEqual((self.directory / 'core').read_bytes(), old)
            self.assertIn(message, self.log.read_text().splitlines())
        self.set_release('v1.2.3-beta.1')
        proc = self.start()
        proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.state.read_text().strip(), 'finished')
        self.assertFalse((self.directory / 'restarted').exists())
        self.write_executable('sleep', '#!/bin/sh\nexit 0\n')
        self.write_executable('ubus', '#!/bin/sh\necho "{}"\n')
        for rc, enabled in [(1, '1'), (0, 'on')]:
            self.env['ENABLED'] = enabled
            service.write_text(f'#!/bin/sh\ntouch "$TEST_DIR/restarted"\nexit {rc}\n')
            proc = self.start('force')
            proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 1)
            self.assertTrue((self.directory / 'restarted').exists())
            self.assertEqual(self.state.read_text().strip(), 'start_failed')
            (self.directory / 'restarted').unlink()

    def test_asset_api_download_and_fallback(self):
        version = 'v1.0.0'
        old = self.write_executable('core', '#!/bin/sh\necho "AdGuard Home, version v0.107.80"\n').read_bytes()
        self.make_archive(version)
        digest = 'sha256:' + hashlib.sha256((self.directory / 'core.tar.gz').read_bytes()).hexdigest()
        (self.directory / 'release').touch()
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/restarted"\nexit 1\n')
        api = 'https://api.github.com/repos/AdguardTeam/AdGuardHome/releases/assets/123'
        direct = 'https://test/core'
        requests = self.directory / 'requests'
        for label, asset_id, fail_api, fail_direct, checksum, expected_urls, success in [
            ('api', 123, False, True, digest, [api], True),
            ('fallback', 123, True, False, digest, [api, direct], True),
            ('invalid-id', 'bad', False, False, digest, [direct], True),
            ('both-failed', 123, True, True, digest, [api, direct], False),
            ('checksum', 123, False, False, 'sha256:bad', [api], False),
        ]:
            with self.subTest(label=label):
                self.set_release(version, id=asset_id, digest=checksum)
                (self.directory / 'core').write_bytes(old)
                requests.unlink(missing_ok=True)
                self.env.update(FAIL_API=str(int(fail_api)), FAIL_DIRECT=str(int(fail_direct)),
                                ENABLED='0' if success else '1')
                proc = self.start()
                proc.communicate(timeout=5)
                self.assertEqual(requests.read_text().splitlines(), expected_urls)
                self.assertEqual(proc.returncode, 0 if success else 1)
                self.assertEqual(self.state.read_text().strip(), 'finished' if success else 'failure')
                expected_core = (self.directory / 'candidate').read_bytes() if success else old
                self.assertEqual((self.directory / 'core').read_bytes(), expected_core)
                self.assertFalse((self.directory / 'restarted').exists())
                if label == 'both-failed':
                    log = self.log.read_text().splitlines()
                    self.assertIn(f'Download URL: {api}', log)
                    self.assertIn(f'Download URL: {direct}', log)
                    self.assertIn('Download failed (uclient-fetch exit code): 4', log)
                    self.assertIn('Connection error: Connection timed out', log)

    def test_openwrt_architectures_match_release_asset_names(self):
        source = self.script.read_text()
        lookup = source[source.index('get_arch()'):source.index('core_version()')] + '\nget_arch'
        self.write_executable('uname', '#!/bin/sh\necho "${MACHINE:-x86_64}"\n')
        cases = {
            'x86_64': 'amd64', 'i386_pentium4': '386', 'i686': '386',
            'aarch64_cortex-a53': 'arm64', 'arm_cortex-a7_neon-vfpv4': 'armv7',
            'arm_arm1176jzf-s_vfp': 'armv6', 'arm_xscale': 'armv5',
            'mips_24kc': 'mips_softfloat', 'mipsel_24kc': 'mipsle_softfloat',
            'mips64_octeonplus': 'mips64_softfloat', 'mips64el_mips64r2': 'mips64le_softfloat',
            'powerpc64le': 'ppc64le', 'riscv64_generic': 'riscv64',
            'armeb': '', 'aarch64_be': '', 'arm_fa526': '',
        }
        for package_manager in ('apk', 'opkg'):
            if package_manager == 'opkg':
                (self.directory / 'apk').unlink()
                self.write_executable('opkg', '#!/bin/sh\nprintf "arch all 1\\narch noarch 2\\narch %s 10\\n" "$ARCH"\n')
            for arch, expected in cases.items():
                with self.subTest(package_manager=package_manager, arch=arch):
                    result = subprocess.run(['sh', '-c', lookup], capture_output=True, text=True,
                                            env=dict(self.env, PATH=str(self.directory) + ':/usr/bin:/bin', ARCH=arch))
                    self.assertEqual(result.stdout.strip(), expected)
                    self.assertEqual(result.returncode, 0 if expected else 1)


if __name__ == '__main__':
    unittest.main()
