"""在隔离的核心和 YAML 上验证更新, 备份, 恢复以及锁的行为."""
import hashlib
import json
import os
from pathlib import Path
import shutil
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
[ "$1" != "-q" ] || shift
case "$2" in
*.binpath) echo "${BIN_PATH:-$TEST_DIR/core}";;
*.configpath) echo "${CONFIG_PATH:-$TEST_DIR/settings/current.yaml}";;
*.workdir) echo "${WORK_DIR:-$TEST_DIR}";;
*.enabled) echo "${ENABLED:-0}";;
esac
''')
        self.core = self.write_executable('core', '#!/bin/sh\necho "AdGuardHome version v1.2.3"\n')
        self.yaml = self.directory / 'settings/current.yaml'
        self.yaml.parent.mkdir()
        self.yaml.write_bytes(b'http:\n  address: 127.0.0.1:3000\n')
        self.history = self.directory / 'core.backups'
        self.uploads = self.directory / 'uploads'
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
        scripts = ROOT / 'root/usr/share/AdGuardHome'
        helper = self.directory / 'core_backup.sh'
        helper.write_text((scripts / helper.name).read_text().replace('/etc/init.d/AdGuardHome', '"$TEST_DIR/service"'))
        source = (scripts / 'update_core.sh').read_text()
        source = source.replace('/usr/share/AdGuardHome/core_backup.sh', str(helper))
        source = source.replace('/var/run/AdGuardHome-uploads', str(self.uploads))
        source = source.replace('PATH="/usr/sbin:/usr/bin:/sbin:/bin"',
                                'PATH="$TEST_DIR:/usr/bin:/bin"')
        for path in ['/var/lock/AdGuardHome-update.lock', '/var/run/AdGuardHome-update.state',
                     '/tmp/AdGuardHome_update.log', '/tmp/AdGuardHome-update.XXXXXX']:
            source = source.replace(path, str(self.directory / Path(path).name))
        source = source.replace('/etc/init.d/AdGuardHome', '"$TEST_DIR/service"')
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

    def install_validating_core(self, version):
        # 模拟不同核心支持的配置及核心校验时可能执行的 YAML 迁移.
        return self.write_executable('core', f'''#!/usr/bin/env python3
import argparse, json, os, sys
from pathlib import Path
version = {version!r}
if sys.argv[1:] == ['--version']:
    print('AdGuardHome version', version)
    sys.exit(0)
parser = argparse.ArgumentParser()
parser.add_argument('--check-config', action='store_true', required=True)
parser.add_argument('-c', '--config', type=Path, required=True)
parser.add_argument('-w', '--work-dir', required=True)
parser.add_argument('-l', '--logfile', required=True)
args = parser.parse_args()
if (args.work_dir != os.environ.get('WORK_DIR', os.environ['TEST_DIR']) or
        not Path(args.work_dir).is_dir() or args.logfile != os.devnull):
    sys.exit(2)
content = args.config.read_text()
with (Path(os.environ['TEST_DIR']) / 'checks').open('a') as log:
    print(json.dumps([version, str(args.config.resolve()), content]), file=log)
if content == 'http: [\\n' or ('requires: ' in content and version not in content):
    sys.exit(1)
args.config.write_text('schema_version: migrated\\n')
''')

    def config_checks(self):
        records = self.directory / 'checks'
        return [json.loads(line) for line in records.read_text().splitlines()] if records.exists() else []

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

    def check_action(self, expected_state, *args, returncode=0):
        proc = self.start(*args)
        proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, returncode, self.log.read_text())
        self.assertEqual(self.state.read_text().strip(), expected_state, self.log.read_text())

    def test_normal_and_force_contenders_preserve_owner_state(self):
        owner = self.start()
        self.wait_ready()
        before = self.log.read_bytes()
        for args in [(), ('force',), ('--background', 'backup-core'), ('backup-config',),
                     ('restore-core', 'legacy'), ('restore-config', '1800000000-0001'),
                     ('--background', 'delete', 'legacy'), ('--background', 'upload', 'ABC123')]:
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

    def entries(self):
        return set(self.history.glob('[0-9]*'))

    def check_new_entry(self, state, *action):
        previous = self.entries()
        self.check_action(state, *action)
        added = self.entries() - previous
        self.assertEqual(len(added), 1)
        entry = added.pop()
        self.assertRegex(entry.name, r'^[0-9]{10}-[0-9]{4}$')
        return entry

    def assert_snapshot(self, entry, source, version, core, config):
        self.assertEqual((entry / 'core').read_bytes(), core)
        self.assertEqual((entry / 'config.yaml').read_bytes(), config)
        self.assertEqual((entry / 'meta').read_text().split(),
                         [source, version, hashlib.sha256(core).hexdigest(), hashlib.sha256(config).hexdigest()])

    def create_legacy(self):
        image = self.directory / 'core.prev'
        image.write_bytes(self.core.read_bytes())
        metadata = self.directory / 'core.prev.meta'
        metadata.write_text('v1.2.3 ' + hashlib.sha256(image.read_bytes()).hexdigest() + '\n')
        return image, metadata

    def upload_payload(self):
        self.uploads.mkdir(mode=0o700, exist_ok=True)
        ready = self.uploads / 'ready.ABC123'
        ready.mkdir(mode=0o700)
        return ready / 'payload'

    def test_uploaded_core_installs_offline_and_validates_config_before_backup(self):
        candidate = self.directory / 'fixture-elf'
        subprocess.run(['cc', '-x', 'c', '-', '-o', candidate], check=True, input=b'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts(getenv("WRONG_VERSION") ? "fixture version v7.8.9" : "AdGuard Home, version v7.8.9-test");
        return 0;
    }
    return argc > 2 && strcmp(argv[1], "--check-config") == 0 && !getenv("INVALID_CONFIG") ? 0 : 1;
}
''')
        # 用单独的命令模拟 Go 构建记录. 测试 ELF 本身不会被真实更新器当作核心安装.
        self.write_executable('strings', '''#!/bin/sh
cmp -s "$1" "$TEST_DIR/fixture-elf" || exit 1
printf 'path\tgithub.com/AdguardTeam/AdGuardHome\nbuild\tGOOS=linux\n'
''')
        self.write_executable('uclient-fetch', '#!/bin/sh\ntouch "$TEST_DIR/network-used"\nexit 1\n')
        original_core, yaml = self.core.read_bytes(), self.yaml.read_bytes()
        for flag in ('WRONG_VERSION', 'INVALID_CONFIG'):
            self.env[flag] = '1'
            payload = self.upload_payload()
            shutil.copyfile(candidate, payload)
            self.check_action('failure', 'upload', 'ABC123', returncode=1)
            self.assertFalse(payload.parent.exists() or self.entries())
            self.assertEqual(self.core.read_bytes(), original_core)
            del self.env[flag]

        for member in ('', './AdGuardHome/AdGuardHome', 'AdGuardHome/AdGuardHome'):
            with self.subTest(member=member):
                payload = self.upload_payload()
                if member:
                    with tarfile.open(payload, 'w:gz') as archive:
                        archive.add(candidate, arcname=member)
                else:
                    shutil.copyfile(candidate, payload)
                checksum = hashlib.sha256(payload.read_bytes()).hexdigest()
                backup = self.check_new_entry('finished', 'upload', 'ABC123', checksum.upper() if member else checksum)
                self.assert_snapshot(backup, 'update', 'v7.8.9-test' if member else 'v1.2.3', original_core, yaml)
                self.assertIn('Uploaded file SHA-256 verified.', self.log.read_text())
                self.assertIn('Uploaded AdGuard Home version: v7.8.9-test', self.log.read_text())
                self.assertEqual(self.core.read_bytes(), candidate.read_bytes())
                self.assertFalse(payload.parent.exists() or (self.directory / 'network-used').exists())
                original_core = candidate.read_bytes()
        self.core.unlink()
        self.yaml.unlink()
        backups = self.entries()
        shutil.copyfile(candidate, self.upload_payload())
        self.check_action('finished', 'upload', 'ABC123', '')
        self.assertNotIn('SHA-256', self.log.read_text())
        self.assertEqual(self.entries(), backups)
        self.assertFalse(self.yaml.exists())

        self.core.write_bytes(b'broken')
        self.yaml.write_bytes(yaml)
        shutil.copyfile(candidate, self.upload_payload())
        snapshot = self.check_new_entry('finished', 'upload', 'ABC123', hashlib.sha256(candidate.read_bytes()).hexdigest())
        self.assertEqual((snapshot / 'damaged-core').read_bytes(), b'broken')
        self.assertEqual((snapshot / 'config.yaml').read_bytes(), yaml)
        self.assertEqual(self.core.read_bytes(), candidate.read_bytes())

    def test_repair_preserves_damaged_files_and_requires_a_valid_backup(self):
        self.make_archive('v1.2.3')
        (self.directory / 'release').touch()
        self.core.write_bytes(b'')
        yaml = self.yaml.read_bytes()
        self.check_action('failure', returncode=1)
        self.assertIn('Use Force update or Upload core', self.log.read_text())
        self.assertFalse(self.entries())

        # 模拟写入保全副本失败, 确认不会提前替换原件.
        copy = self.write_executable('cp', '''#!/bin/sh
case "$2" in */damaged-core) exit 1;; esac
exec /bin/cp "$@"
''')
        self.check_action('failure', 'force', returncode=1)
        self.assertFalse(self.entries())
        self.assertEqual(self.core.read_bytes(), b'')
        self.assertEqual(self.yaml.read_bytes(), yaml)
        copy.unlink()

        snapshot = self.check_new_entry('finished', 'force')
        self.assertEqual((snapshot / 'meta').read_text().split(),
                         ['update', 'damaged', hashlib.sha256(b'').hexdigest(), hashlib.sha256(yaml).hexdigest()])
        self.assertEqual((snapshot / 'damaged-core').read_bytes(), b'')
        self.assertEqual((snapshot / 'damaged-core').stat().st_mode & 0o777, 0o600)
        working = self.core.read_bytes()
        for action in ('restore-core', 'restore'):
            self.check_action('restore_failed', action, snapshot.name, returncode=1)
            self.assertEqual(self.core.read_bytes(), working)
        self.yaml.write_text('changed')
        self.check_action('restored', 'restore-config', snapshot.name)
        self.assertEqual(self.yaml.read_bytes(), yaml)

        self.yaml.unlink()
        self.core.write_bytes(b'unusable')
        core_only = self.check_new_entry('finished', 'force')
        self.assertEqual((core_only / 'meta').read_text().split()[-1], '-')
        self.assertEqual((core_only / 'damaged-core').read_bytes(), b'unusable')
        self.assertFalse(self.yaml.exists())
        self.check_action('deleted', 'delete', core_only.name)
        self.assertFalse(core_only.exists())
        self.yaml.write_bytes(yaml)
        for _ in range(3):
            self.check_action('finished', 'force')
        self.assertFalse(snapshot.exists())
        self.assertEqual(len(self.entries()), 3)

    def test_interrupted_upload_tracks_and_locks_its_own_extract_directory(self):
        payload = self.upload_payload()
        payload.write_bytes(b'\x1f\x8barchive fixture')
        self.write_executable('tar', '''#!/bin/sh
echo extracting
touch "$TEST_DIR/ready"
exec sleep 30
''')
        worker = self.start('upload', 'ABC123')
        self.wait_ready()
        stage = (payload.parent / '.stage').resolve(strict=True)
        self.assertEqual(stage.parent, self.core.parent)
        self.assertEqual((stage / '.upload-owner').read_text().strip(), str(payload.parent))
        self.assertEqual((stage / 'core').read_text(), 'extracting\n')
        self.assertNotEqual(subprocess.run(['flock', '-n', payload.parent, 'true']).returncode, 0)
        os.killpg(worker.pid, signal.SIGKILL)
        worker.communicate(timeout=5)
        self.assertEqual(subprocess.run(['flock', '-n', payload.parent, 'true']).returncode, 0)
        self.assertTrue((payload.parent / '.stage').exists())

    def test_uploaded_file_sha256_failure_stops_before_extraction_or_install(self):
        original_core, yaml = self.core.read_bytes(), self.yaml.read_bytes()
        self.env['ENABLED'] = '1'
        self.write_executable('tar', '#!/bin/sh\ntouch "$TEST_DIR/extracted"\nexit 1\n')
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/service-used"\nexit 1\n')
        self.make_archive('v1.2.4')
        archive = self.directory / 'core.tar.gz'
        core_digest = hashlib.sha256((self.directory / 'candidate').read_bytes()).hexdigest()
        for source, digest in ((self.core, '0' * 64), (archive, core_digest),
                               (archive, 'abc'), (archive, 'g' * 64)):
            with self.subTest(source=source.name, digest=digest):
                payload = self.upload_payload()
                shutil.copyfile(source, payload)
                self.check_action('failure', 'upload', 'ABC123', digest, returncode=1)
                self.assertIn('Uploaded file SHA-256 verification failed.', self.log.read_text())
                self.assertFalse(payload.parent.exists() or self.entries())
                self.assertFalse((self.directory / 'extracted').exists() or (self.directory / 'service-used').exists())
                self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), (original_core, yaml))

    def test_uploaded_core_rejects_unrelated_files_archives_and_oversize_payloads(self):
        original_core, yaml = self.core.read_bytes(), self.yaml.read_bytes()
        # 为大小限制测试使用同一套代码, 以较小数据覆盖压缩和解压后的边界.
        self.script.write_text(self.script.read_text().replace('upload_limit=134217728', 'upload_limit=65536'))
        for kind in ('script', 'unrelated', 'foreign', 'empty', 'large', 'archive', 'expanded', 'symlink'):
            with self.subTest(kind=kind):
                p = self.upload_payload()
                if kind == 'script':
                    p.write_text('#!/bin/sh\necho fixture\n')
                elif kind in ('unrelated', 'foreign'):
                    elf = bytearray(Path('/bin/true').read_bytes())
                    if kind == 'foreign':
                        elf[5] = 3 - elf[5]
                    p.write_bytes(elf)
                elif kind == 'symlink':
                    p.symlink_to(self.yaml)
                elif kind in ('large', 'empty'):
                    p.write_bytes(b'x' * (65537 if kind == 'large' else 0))
                else:
                    data = self.directory / 'packed'
                    data.write_bytes(b'a' * (66000 if kind == 'expanded' else 16))
                    with tarfile.open(p, 'w:gz') as archive:
                        archive.add(data, arcname='AdGuardHome/AdGuardHome' if kind == 'expanded' else 'other')
                self.check_action('failure', 'upload', 'ABC123', returncode=1)
                self.assertFalse(p.parent.exists() or self.entries())
                self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), (original_core, yaml))
                if kind == 'unrelated':
                    self.assertIn('not an AdGuard Home Linux core', self.log.read_text())
                if kind == 'expanded':
                    self.assertIn('128 MiB limit', self.log.read_text())
        p = self.upload_payload()
        p.write_bytes(b'private')
        self.check_action('failure', 'upload', '../ready.ABC123', returncode=1)
        self.assertEqual(p.read_bytes(), b'private')

    def test_update_snapshots_previous_pair_after_validation(self):
        old_yaml = self.yaml.read_bytes()
        self.core.unlink()
        (self.directory / 'release').touch()
        self.make_archive('v1.2.3')
        self.check_action('finished')
        self.assertFalse(self.entries())
        self.check_action('current')
        self.assertFalse(self.entries())

        first = self.core.read_bytes()
        forced = self.check_new_entry('finished', 'force')
        self.assert_snapshot(forced, 'update', 'v1.2.3', first, old_yaml)
        self.yaml.write_bytes(b'http:\n  address: 127.0.0.1:3010\n')
        self.set_release('v1.2.4')
        self.make_archive('v1.2.4')
        upgrade = self.check_new_entry('finished')
        self.assert_snapshot(upgrade, 'update', 'v1.2.3', first, self.yaml.read_bytes())
        self.assertNotEqual(first, self.core.read_bytes())

        second = self.core.read_bytes()
        self.set_release('v1.2.5', digest='sha256:bad')
        self.make_archive('v1.2.5')
        self.check_action('failure', returncode=1)
        self.assertEqual(self.core.read_bytes(), second)
        self.assertEqual(self.entries(), {forced, upgrade})
        self.assert_snapshot(forced, 'update', 'v1.2.3', first, old_yaml)

    def test_manual_restore_selects_pair_by_id_offline(self):
        self.env['WORK_DIR'] = str(self.yaml.parent)
        self.env['CONFIG_PATH'] = 'selected config.yaml'
        config_link = self.yaml.parent / 'selected config.yaml'
        config_link.symlink_to(self.yaml.name)
        installed = self.directory / 'mounted data/AdGuardHome'
        installed.parent.mkdir()
        self.core.rename(installed)
        self.core.symlink_to(installed.relative_to(self.directory))
        self.history = installed.with_name('AdGuardHome.backups')
        self.write_executable('uclient-fetch', '#!/bin/sh\ntouch "$TEST_DIR/network-used"\nexit 1\n')
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/service-used"\nexit 1\n')
        original = installed.read_bytes()
        first_yaml = self.yaml.read_bytes()
        self.env['ENABLED'] = '1'
        first = self.check_new_entry('backed_up', 'backup')
        self.assert_snapshot(first, 'manual', 'v1.2.3', original, first_yaml)
        self.assertEqual(self.history.stat().st_mode & 0o077, 0)
        self.assertFalse(os.path.samefile(first / 'core', installed))

        self.env['ENABLED'] = '0'
        second_yaml = b'http:\n  address: 127.0.0.1:4000\n'
        self.yaml.write_bytes(second_yaml)
        second = self.check_new_entry('backed_up', 'backup')
        self.assert_snapshot(second, 'manual', 'v1.2.3', original, second_yaml)
        self.assertTrue(os.path.samefile(first / 'core', second / 'core'))
        installed.unlink()
        self.yaml.unlink()
        for entry, config in [(first, first_yaml), (second, second_yaml), (first, first_yaml)]:
            self.check_action('restored', 'restore', entry.name)
            self.assertTrue(self.core.is_symlink())
            self.assertTrue(config_link.is_symlink())
            self.assertEqual(self.core.read_bytes(), original)
            self.assertTrue(os.access(installed, os.X_OK))
            self.assertEqual(self.yaml.read_bytes(), config)
        self.assertFalse((self.directory / 'network-used').exists())
        self.assertFalse((self.directory / 'service-used').exists())

    def test_retention_uses_independent_creation_order_and_preserves_legacy(self):
        self.write_executable('date', '''#!/bin/sh
if [ "$1" = '+%s' ]; then echo "$TEST_TIMESTAMP"; else exec /bin/date "$@"; fi
''')
        self.env['TEST_TIMESTAMP'] = '1800000000'
        image, metadata = self.create_legacy()
        legacy_contents = image.read_bytes(), metadata.read_bytes()
        manual_core = self.check_new_entry('backed_up', 'backup-core')
        manual_config = self.check_new_entry('backed_up', 'backup-config')
        snapshots = []
        (self.directory / 'release').touch()
        self.make_archive('v1.2.3')
        for port in range(3010, 3016):
            if port == 3013:
                self.env['TEST_TIMESTAMP'] = '1799999900'
            self.yaml.write_text(f'http:\n  address: 127.0.0.1:{port}\n')
            snapshots.append(self.check_new_entry('finished', 'force'))
        self.assertEqual(len(set(snapshots)), 6)
        retained = {manual_core, manual_config, *snapshots[-3:]}
        self.assertEqual(self.entries(), retained)
        cores = [manual_core]
        configs = [manual_config]
        for action, records in [('backup-core', cores), ('backup-config', configs)]:
            for _ in range(7):
                records.append(self.check_new_entry('backed_up', action))
                self.assertEqual(self.entries(), {*cores[-5:], *configs[-5:], *snapshots[-3:]})
        retained = self.entries()
        self.assertEqual((image.read_bytes(), metadata.read_bytes()), legacy_contents)
        self.write_executable('mv', '''#!/bin/sh
for target in "$@"; do :; done
case "$target" in "$TEST_DIR/core.backups/"[0-9]*) exit 1 ;; esac
exec /bin/mv "$@"
''')
        self.check_action('failure', 'force', returncode=1)
        self.check_action('backup_failed', 'backup-core', returncode=1)
        self.check_action('backup_failed', 'backup-config', returncode=1)
        self.assertEqual(self.entries(), retained)
        self.assertEqual((image.read_bytes(), metadata.read_bytes()), legacy_contents)
        for expired in snapshots[:-3]:
            self.check_action('restore_failed', 'restore', expired.name, returncode=1)
        self.check_action('restored', 'restore', snapshots[-3].name)
        self.assertIn('3013', self.yaml.read_text())

    def test_manual_pair_retains_each_component_until_its_own_quota_expires(self):
        original_yaml = self.yaml.read_bytes()
        first = self.check_new_entry('backed_up', 'backup')
        # 早期格式没有标记文件, 仍应支持按组件轮换.
        (first / '.snapshot').unlink()
        for _ in range(5):
            self.check_new_entry('backed_up', 'backup-core')
        self.assertFalse((first / 'core').exists())
        self.assertEqual((first / 'config.yaml').read_bytes(), original_yaml)
        self.assertEqual((first / 'meta').read_text().split(),
                         ['manual', '-', '-', hashlib.sha256(original_yaml).hexdigest()])

        current_core = self.write_executable('core', '#!/bin/sh\necho "AdGuardHome version v1.2.4"\n').read_bytes()
        self.yaml.write_text('port: 3010\n')
        self.check_action('restore_failed', 'restore-core', first.name, returncode=1)
        self.check_action('restore_failed', 'restore-both', first.name, returncode=1)
        self.assertEqual(self.yaml.read_text(), 'port: 3010\n')
        self.check_action('restored', 'restore-config', first.name)
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), (current_core, original_yaml))

        second = self.check_new_entry('backed_up', 'backup')
        for _ in range(5):
            self.check_new_entry('backed_up', 'backup-config')
        self.assertFalse(first.exists())
        self.assertFalse((second / 'config.yaml').exists())
        self.assertEqual((second / 'core').read_bytes(), current_core)
        self.assertEqual((second / 'meta').read_text().split(),
                         ['manual', 'v1.2.4', hashlib.sha256(current_core).hexdigest(), '-'])
        self.core.unlink()
        self.yaml.write_bytes(b'port: 3020\n')
        self.check_action('restore_failed', 'restore-config', second.name, returncode=1)
        self.check_action('restore_failed', 'restore-both', second.name, returncode=1)
        self.assertFalse(self.core.exists())
        self.check_action('restored', 'restore-core', second.name)
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), (current_core, b'port: 3020\n'))

    def test_failed_manual_pair_pruning_can_retry_without_losing_backups(self):
        pair = self.check_new_entry('backed_up', 'backup')
        core, config = self.core.read_bytes(), self.yaml.read_bytes()
        recent = [self.check_new_entry('backed_up', 'backup-config') for _ in range(4)]
        self.env['BLOCK_META'] = str(pair / 'meta')
        rename = self.write_executable('mv', '''#!/bin/sh
for target in "$@"; do :; done
[ "$target" != "$BLOCK_META" ] || exit 1
exec /bin/mv "$@"
''')
        recent.append(self.check_new_entry('backed_up', 'backup-config'))
        self.assertEqual(self.entries(), {pair, *recent})
        self.assert_snapshot(pair, 'manual', 'v1.2.3', core, config)
        self.check_action('restored', 'restore', pair.name)
        rename.unlink()

        self.env['BLOCK_YAML'] = str(pair / 'config.yaml')
        remove = self.write_executable('rm', '''#!/bin/sh
for target in "$@"; do [ "$target" != "$BLOCK_YAML" ] || exit 1; done
exec /bin/rm "$@"
''')
        recent.append(self.check_new_entry('backed_up', 'backup-config'))
        self.assertTrue((pair / 'config.yaml').is_file())
        self.check_action('restore_failed', 'restore-config', pair.name, returncode=1)
        self.check_action('restored', 'restore-core', pair.name)
        remove.unlink()
        recent.append(self.check_new_entry('backed_up', 'backup-config'))
        self.assertEqual(self.entries(), {pair, *recent[-5:]})
        self.assertEqual((pair / 'core').read_bytes(), core)
        self.assertFalse((pair / 'config.yaml').exists())

    def test_delete_selected_snapshot_preserves_shared_core_and_active_files(self):
        image, metadata = self.create_legacy()
        selected = self.check_new_entry('backed_up', 'backup')
        (self.directory / 'release').touch()
        self.make_archive('v1.2.3')
        retained = self.check_new_entry('finished', 'force')
        self.assertTrue(os.path.samefile(selected / 'core', retained / 'core'))
        original = self.core.read_bytes(), self.yaml.read_bytes()
        snapshot = (retained / 'core').read_bytes(), (retained / 'config.yaml').read_bytes()
        self.env['ENABLED'] = '1'
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/service-used"\nexit 1\n')
        pending = self.directory / 'core.restore-pending'
        pending.mkdir(mode=0o700)
        journal = {'previous-core': 'prior core', 'previous-yaml': 'prior: yaml\n',
                   'config-path': str(self.yaml) + '\n', 'was-running': '',
                   'core-stage': '.AdGuardHome.123456\n', 'yaml-stage': '.AdGuardHome.234567\n'}
        for name, content in journal.items():
            (pending / name).write_text(content)

        self.check_action('rollback_failed', 'delete', selected.name, returncode=1)
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), original)
        self.assertEqual({file.name: file.read_text() for file in pending.iterdir()}, journal)
        self.assertFalse((self.directory / 'service-used').exists())
        shutil.rmtree(pending)
        self.check_action('deleted', 'delete', selected.name)
        self.assertEqual(self.entries(), {retained})
        self.assertEqual((retained / 'core').stat().st_nlink, 1)
        self.assert_snapshot(retained, 'update', 'v1.2.3', *snapshot)
        self.assertTrue(image.is_file() and metadata.is_file())
        for invalid_id in (selected.name, '', '../' + retained.name, '.ids'):
            with self.subTest(id=invalid_id):
                self.check_action('delete_failed', 'delete', invalid_id, returncode=1)
                self.assertEqual(self.entries(), {retained})
        extra = retained / 'notes'
        extra.write_text('keep')
        self.check_action('delete_failed', 'delete', retained.name, returncode=1)
        self.assertEqual(extra.read_text(), 'keep')
        self.assert_snapshot(retained, 'update', 'v1.2.3', *snapshot)
        extra.unlink()
        self.check_action('deleted', 'delete', retained.name)
        self.assertFalse(self.entries())
        self.check_action('deleted', 'delete', 'legacy')
        self.assertFalse(image.exists())
        self.assertFalse(metadata.exists())
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), original)
        self.assertFalse((self.directory / 'service-used').exists())

    def test_delete_rejects_backups_used_as_active_yaml(self):
        snapshot = self.check_new_entry('backed_up', 'backup-config')
        legacy, _metadata = self.create_legacy()
        link = self.directory / 'active.yaml'
        for backup_id, target in ((snapshot.name, snapshot / 'config.yaml'), ('legacy', legacy)):
            content = target.read_bytes()
            link.symlink_to(target)
            for config in (target, link):
                with self.subTest(backup=backup_id, config=config):
                    self.env['CONFIG_PATH'] = str(config)
                    self.check_action('delete_failed', 'delete', backup_id, returncode=1)
                    self.assertEqual(config.read_bytes(), content)
            link.unlink()

    def test_delete_legacy_respects_its_published_files(self):
        kept = self.check_new_entry('backed_up', 'backup-config')
        for staged in (True, False):
            with self.subTest(staged=staged):
                image, metadata = self.create_legacy()
                next_meta = self.directory / 'core.prev.meta.new'
                next_meta.write_bytes(metadata.read_bytes())
                next_image = self.directory / 'core.prev.new'
                if staged:
                    next_image.write_bytes(b'next image')
                self.check_action('deleted', 'delete', 'legacy')
                self.assertFalse(image.exists())
                self.assertFalse(metadata.exists())
                self.assertEqual(next_meta.exists(), staged)
                self.assertEqual(next_image.exists(), staged)
                if staged:
                    self.assertEqual(next_image.read_bytes(), b'next image')
                    next_image.unlink()
                    next_meta.unlink()
                self.assertEqual(self.entries(), {kept})

    def test_legacy_restore_preserves_current_yaml(self):
        image, metadata = self.create_legacy()
        original = self.core.read_bytes()
        self.core.unlink()
        before = self.yaml.read_bytes(), self.yaml.stat().st_mtime_ns
        self.check_action('restore_failed', 'restore-config', 'legacy', returncode=1)
        self.assertFalse(self.core.exists())
        for action in ('restore', 'restore-core'):
            self.check_action('restored', action, 'legacy')
            self.assertEqual(self.core.read_bytes(), original)
        self.assertEqual((self.yaml.read_bytes(), self.yaml.stat().st_mtime_ns), before)
        self.assertFalse(self.entries())
        metadata.write_text('v1.2.3 incomplete\n')
        self.check_action('restore_failed', 'restore', 'legacy', returncode=1)
        self.assertEqual((self.core.read_bytes(), image.read_bytes()), (original, original))

    def test_manual_components_work_without_the_other_file(self):
        original_core, original_yaml = self.core.read_bytes(), self.yaml.read_bytes()
        self.yaml.unlink()
        core = self.check_new_entry('backed_up', 'backup-core')
        self.assertEqual((core / 'core').read_bytes(), original_core)
        self.assertFalse((core / 'config.yaml').exists())
        self.assertEqual((core / 'meta').read_text().split(),
                         ['manual', 'v1.2.3', hashlib.sha256(original_core).hexdigest(), '-'])
        self.check_action('backup_failed', 'backup-config', returncode=1)
        self.check_action('restore_failed', 'restore-config', core.name, returncode=1)
        self.assertFalse(self.yaml.exists())
        self.core.unlink()
        self.check_action('restored', 'restore-core', core.name)
        self.assertEqual(self.core.read_bytes(), original_core)
        self.assertFalse(self.yaml.exists())

        missing_core = self.directory / 'fresh install/AdGuardHome'
        self.env['BIN_PATH'] = str(missing_core)
        self.history = missing_core.with_name('AdGuardHome.backups')
        self.env['ENABLED'] = '1'
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/service-used"\nexit 1\n')
        self.yaml.write_bytes(original_yaml)
        config = self.check_new_entry('backed_up', 'backup-config')
        self.assertIn('YAML validation skipped: no core is installed.', self.log.read_text())
        self.assertEqual((config / 'config.yaml').read_bytes(), original_yaml)
        self.assertFalse((config / 'core').exists())
        self.assertEqual((config / 'meta').read_text().split(),
                         ['manual', '-', '-', hashlib.sha256(original_yaml).hexdigest()])
        self.yaml.unlink()
        self.check_action('backup_failed', 'backup-core', returncode=1)
        self.check_action('restore_failed', 'restore-core', config.name, returncode=1)
        self.check_action('restored', 'restore-config', config.name)
        self.assertIn('YAML validation skipped: no core is installed.', self.log.read_text())
        self.assertEqual(self.yaml.read_bytes(), original_yaml)
        self.assertFalse(missing_core.exists())
        self.assertFalse((self.directory / 'service-used').exists())
        self.assertFalse((self.directory / 'ready').exists())

    def test_yaml_backup_validates_private_copy_before_publication_and_update(self):
        self.install_validating_core('v1.2.3')
        workdir = self.directory / 'work dir'
        self.env['WORK_DIR'] = str(workdir)
        original_core = self.core.read_bytes()
        original_yaml = self.yaml.read_text()
        entry = self.check_new_entry('backed_up', 'backup-config')
        self.assertTrue(workdir.is_dir())
        [(version, checked_path, content)] = self.config_checks()
        self.assertEqual((version, content), ('v1.2.3', original_yaml))
        self.assertNotEqual(Path(checked_path), self.yaml)
        self.assertEqual((entry / 'config.yaml').read_text(), original_yaml)
        self.assertEqual(self.yaml.read_text(), original_yaml)

        self.yaml.write_text('http: [\n')
        core_entry = self.check_new_entry('backed_up', 'backup-core')
        self.check_action('restored', 'restore-core', core_entry.name)
        self.assertEqual(len(self.config_checks()), 1)
        self.set_release('v1.2.4')
        self.make_archive('v1.2.4')
        (self.directory / 'release').touch()
        self.env['ENABLED'] = '1'
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/service-used"\nexit 1\n')
        for args, state in [(('backup-config',), 'backup_failed'), ((), 'failure')]:
            with self.subTest(args=args):
                before = len(self.config_checks())
                self.check_action(state, *args, returncode=1)
                [(version, checked_path, content)] = self.config_checks()[before:]
                self.assertEqual((version, content), ('v1.2.3', 'http: [\n'))
                self.assertNotEqual(Path(checked_path), self.yaml)
                self.assertIn('YAML configuration validation failed.', self.log.read_text())
                self.assertEqual(self.entries(), {entry, core_entry})
                self.assertEqual(self.core.read_bytes(), original_core)
                self.assertEqual(self.yaml.read_text(), 'http: [\n')
                self.assertFalse((self.directory / 'service-used').exists())

    def test_yaml_validation_reports_unavailable_workdir(self):
        self.install_validating_core('v1.2.3')
        self.env['WORK_DIR'] = str(self.yaml / 'not-a-directory')
        self.check_action('backup_failed', 'backup-config', returncode=1)
        self.assertIn('Unable to prepare the configured working directory.', self.log.read_text())
        self.assertNotIn('YAML configuration validation failed.', self.log.read_text())
        self.assertFalse(self.config_checks() or self.entries())

    def test_yaml_restore_validates_with_the_core_that_will_use_it(self):
        self.install_validating_core('v1.2.3')
        saved = 'requires: v1.2.3\n'
        self.yaml.write_text(saved)
        entry = self.check_new_entry('backed_up', 'backup')
        self.install_validating_core('v1.2.4')
        live_core = self.core.read_bytes()
        self.yaml.write_text('requires: v1.2.4\n')
        self.env['ENABLED'] = '1'
        self.write_executable('ubus', '#!/bin/sh\necho 1234\n')
        self.write_executable('jsonfilter', '#!/bin/sh\ncat\n')
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/service-used"\nexit 1\n')
        self.check_action('restore_failed', 'restore-config', entry.name, returncode=1)
        version, checked_path, content = self.config_checks()[-1]
        self.assertEqual((version, content), ('v1.2.4', saved))
        self.assertNotIn(Path(checked_path), (self.yaml, entry / 'config.yaml'))
        self.assertIn('YAML configuration validation failed.', self.log.read_text())
        self.assertEqual(self.core.read_bytes(), live_core)
        self.assertEqual(self.yaml.read_text(), 'requires: v1.2.4\n')
        self.assertFalse((self.directory / 'service-used').exists())

        self.env['ENABLED'] = '0'
        self.write_executable('ubus', '#!/bin/sh\nexit 0\n')
        self.check_action('restored', 'restore-both', entry.name)
        self.assertEqual([check[0] for check in self.config_checks()], ['v1.2.3', 'v1.2.4', 'v1.2.3'])
        self.assertEqual((entry / 'config.yaml').read_text(), saved)
        self.assertEqual(self.yaml.read_text(), saved)
        self.assertEqual(self.core.read_bytes(), (entry / 'core').read_bytes())

    def test_non_executable_core_does_not_skip_yaml_validation(self):
        entry = self.check_new_entry('backed_up', 'backup-config')
        self.core.chmod(0o644)
        self.yaml.write_text('http: [\n')
        for args, state in [(('backup-config',), 'backup_failed'), (('restore-config', entry.name), 'restore_failed')]:
            with self.subTest(args=args):
                self.check_action(state, *args, returncode=1)
                self.assertIn('YAML configuration validation failed.', self.log.read_text())
                self.assertNotIn('YAML validation skipped', self.log.read_text())
                self.assertEqual(self.entries(), {entry})
                self.assertEqual(self.yaml.read_text(), 'http: [\n')

    def test_selective_restore_uses_only_requested_part_of_update(self):
        original_core, original_yaml = self.core.read_bytes(), self.yaml.read_bytes()
        (self.directory / 'release').touch()
        self.set_release('v1.2.4')
        self.make_archive('v1.2.4')
        entry = self.check_new_entry('finished')
        self.assert_snapshot(entry, 'update', 'v1.2.3', original_core, original_yaml)

        new_yaml = b'http:\n  address: 127.0.0.1:4001\n'
        self.yaml.write_bytes(new_yaml)
        unchanged = self.yaml.stat()
        (entry / 'config.yaml').unlink()
        self.check_action('restore_failed', 'restore-both', entry.name, returncode=1)
        self.check_action('restored', 'restore-core', entry.name)
        self.assertEqual(self.core.read_bytes(), original_core)
        self.assertEqual(self.yaml.read_bytes(), new_yaml)
        self.assertEqual((self.yaml.stat().st_ino, self.yaml.stat().st_mtime_ns),
                         (unchanged.st_ino, unchanged.st_mtime_ns))

        (entry / 'config.yaml').write_bytes(original_yaml)
        (entry / 'core').write_bytes(b'corrupt')
        unchanged = self.core.stat()
        self.check_action('restore_failed', 'restore-core', entry.name, returncode=1)
        self.check_action('restored', 'restore-config', entry.name)
        self.assertEqual(self.yaml.read_bytes(), original_yaml)
        self.assertEqual(self.core.read_bytes(), original_core)
        self.assertEqual((self.core.stat().st_ino, self.core.stat().st_mtime_ns),
                         (unchanged.st_ino, unchanged.st_mtime_ns))

    def test_failed_selective_restore_protects_yaml_and_unselected_core(self):
        entry = self.check_new_entry('backed_up', 'backup')
        current_core = b'#!/bin/sh\necho "AdGuardHome version v1.2.4"\n'
        current_yaml = b'http:\n  address: 127.0.0.1:4000\n'
        self.env['ENABLED'] = '1'
        # 恢复核心时启动过程会改写 YAML, 仅恢复配置时则需保留外部换入的核心.
        self.write_executable('service', '''#!/bin/sh
if [ "$1" = restart ]; then
    mv "$TEST_DIR/external" "$OTHER_PATH" || exit 2
    exit 1
fi
''')
        for component, other_file, replacement in [
            ('config', self.core, '#!/bin/sh\necho "AdGuardHome version v1.2.5"\n'),
            ('core', self.yaml, 'http:\n  address: 127.0.0.1:5555\n')
        ]:
            with self.subTest(component=component):
                self.core.write_bytes(current_core)
                self.yaml.write_bytes(current_yaml)
                self.env['OTHER_PATH'] = str(other_file)
                self.write_executable('external', replacement)
                self.check_action('restore_start_failed', 'restore-' + component, entry.name, returncode=1)
                self.assertEqual(self.yaml.read_bytes(), current_yaml)
                if component == 'config':
                    self.assertEqual(other_file.read_text(), replacement)
                else:
                    self.assertEqual(self.core.read_bytes(), current_core)
                self.assertFalse((self.directory / 'core.restore-pending').exists())

    def test_corrupt_or_missing_snapshot_preserves_both_files(self):
        entry = self.check_new_entry('backed_up', 'backup')
        self.write_executable('new-core', '#!/bin/sh\necho "AdGuardHome version v1.2.4"\n').replace(self.core)
        self.yaml.write_bytes(b'http:\n  address: 127.0.0.1:5000\n')
        live = self.core.read_bytes(), self.yaml.read_bytes()
        for name in ('config.yaml', 'core', 'meta'):
            with self.subTest(file=name):
                payload = entry / name
                original = payload.read_bytes()
                payload.unlink()
                self.check_action('restore_failed', 'restore', entry.name, returncode=1)
                self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), live)
                payload.write_bytes(original + b'\n' if name == 'core' else b'changed\n')
                self.check_action('restore_failed', 'restore', entry.name, returncode=1)
                self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), live)
                payload.write_bytes(original)
        self.check_action('restored', 'restore', entry.name)
        self.assertNotEqual((self.core.read_bytes(), self.yaml.read_bytes()), live)

    def test_incomplete_backup_blocks_core_replacement(self):
        self.set_release('v1.2.4')
        self.make_archive('v1.2.4')
        (self.directory / 'release').touch()
        self.env['ENABLED'] = '1'
        self.write_executable('service', '#!/bin/sh\ntouch "$TEST_DIR/service-used"\nexit 1\n')
        original = self.core.read_bytes()
        self.yaml.unlink()
        self.check_action('backup_failed', 'backup', returncode=1)
        self.check_action('failure', returncode=1)
        self.assertEqual(self.core.read_bytes(), original)
        self.assertFalse(self.entries())
        self.yaml.write_bytes(b'http:\n  address: 127.0.0.1:3000\n')
        # 用普通文件模拟无法创建快照目录, 即使测试以 root 运行也会得到失败.
        if self.history.is_dir():
            self.history.rmdir()
        self.history.write_text('occupied')
        self.check_action('failure', returncode=1)
        self.assertEqual(self.core.read_bytes(), original)
        self.assertEqual(self.history.read_text(), 'occupied')
        self.assertFalse((self.directory / 'service-used').exists())

    def test_external_core_change_during_download_preserves_backup(self):
        entry = self.check_new_entry('backed_up', 'backup')
        original = self.core.read_bytes()
        self.write_executable('new', '#!/bin/sh\necho "AdGuardHome version v1.2.4"\n').replace(self.core)
        replacement = self.write_executable('external', '#!/bin/sh\necho "AdGuardHome version v1.2.5"\n').read_bytes()
        self.set_release('v1.2.6')
        self.make_archive('v1.2.6')
        (self.directory / 'release').touch()
        (self.directory / 'uclient-fetch').rename(self.directory / 'fetch')
        self.write_executable('uclient-fetch', '''#!/bin/sh
for url in "$@"; do :; done
if [ "$url" = 'https://test/core' ] && [ -f "$TEST_DIR/external" ]; then
    mv "$TEST_DIR/external" "$TEST_DIR/core"
fi
exec "$TEST_DIR/fetch" "$@"
''')
        self.check_action('failure', returncode=1)
        self.assertEqual(self.core.read_bytes(), replacement)
        self.assertEqual(self.entries(), {entry})
        self.assert_snapshot(entry, 'manual', 'v1.2.3', original, self.yaml.read_bytes())
        upgrade = self.check_new_entry('finished')
        self.assert_snapshot(upgrade, 'update', 'v1.2.5', replacement, self.yaml.read_bytes())

    def test_partial_restore_publication_rolls_back_pair(self):
        saved = self.core.read_bytes(), self.yaml.read_bytes()
        entry = self.check_new_entry('backed_up', 'backup')
        self.write_executable('new', '#!/bin/sh\necho "AdGuardHome version v1.2.4"\n').replace(self.core)
        self.yaml.write_bytes(b'http:\n  address: 127.0.0.1:4000\n')
        previous = self.core.read_bytes(), self.yaml.read_bytes()
        self.write_executable('mv', '''#!/bin/sh
for target in "$@"; do :; done
case "$target" in
    "$TEST_DIR/core"|"$TEST_DIR/settings/current.yaml")
        if [ -f "$TEST_DIR/first-renamed" ] && [ ! -f "$TEST_DIR/failed-once" ]; then
            touch "$TEST_DIR/failed-once"
            exit 1
        fi
        touch "$TEST_DIR/first-renamed" ;;
esac
exec /bin/mv "$@"
''')
        self.check_action('restore_failed', 'restore', entry.name, returncode=1)
        self.assertTrue((self.directory / 'failed-once').exists())
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), previous)
        self.check_action('restored', 'restore', entry.name)
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), saved)

    def test_failed_background_restore_rolls_back_pair(self):
        entry = self.check_new_entry('backed_up', 'backup')
        self.write_executable('new', '#!/bin/sh\necho "AdGuardHome version v1.2.4"\n').replace(self.core)
        self.yaml.write_bytes(b'http:\n  address: 127.0.0.1:4000\n')
        previous = self.core.read_bytes(), self.yaml.read_bytes()
        self.env['ENABLED'] = '1'
        (self.directory / 'service-pid').write_text('1234\n')
        self.write_executable('ubus', '#!/bin/sh\ncat "$TEST_DIR/service-pid" 2>/dev/null\n')
        self.write_executable('jsonfilter', '#!/bin/sh\ncat\n')
        self.write_executable('service', '''#!/bin/sh
echo "$1" >> "$TEST_DIR/actions"
if [ "$1" = stop ]; then
    rm -f "$TEST_DIR/service-pid"
    exit 0
fi
"$TEST_DIR/core" --version >> "$TEST_DIR/attempted"
cat "$TEST_DIR/settings/current.yaml" >> "$TEST_DIR/attempted"
exit 1
''')
        launcher = self.start('--background', 'restore', entry.name)
        launcher.communicate(timeout=3)
        self.assertEqual(launcher.returncode, 0)
        deadline = time.monotonic() + 5
        while self.state.read_text().strip() in ('', 'running'):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertEqual(self.state.read_text().strip(), 'rollback_start_failed', self.log.read_text())
        self.assertEqual((self.directory / 'actions').read_text().splitlines(), ['stop', 'restart', 'restart'])
        self.assertIn('v1.2.3', (self.directory / 'attempted').read_text())
        self.assertIn('v1.2.4', (self.directory / 'attempted').read_text())
        self.assertIn('127.0.0.1:3000', (self.directory / 'attempted').read_text())
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), previous)
        self.assertEqual(self.entries(), {entry})
        pending = self.directory / 'core.restore-pending'
        self.assertTrue((pending / 'files-restored').is_file())
        self.check_action('rollback_start_failed', 'backup-config', returncode=1)
        self.assertEqual(self.entries(), {entry})
        self.assertTrue(pending.is_dir())
        self.assertIn('original service failed to start', self.log.read_text())
        # 用户修正端口后重试, 文件阶段不能覆盖修正, 服务启动成功才允许创建下一份备份.
        self.yaml.write_text('http:\n  address: 127.0.0.1:5000\n')
        self.write_executable('service', '#!/bin/sh\nexit 0\n')
        self.script.write_text(self.script.read_text().replace('wait_for_core() {', 'wait_for_core() { return 0\n'))
        self.check_action('backed_up', 'backup')
        self.assertFalse(pending.exists())
        self.assertIn('5000', self.yaml.read_text())

    def test_killed_restore_recovers_pair_before_next_backup(self):
        entry = self.check_new_entry('backed_up', 'backup')
        self.write_executable('new', '#!/bin/sh\necho "AdGuardHome version v1.2.4"\n').replace(self.core)
        self.yaml.write_bytes(b'http:\n  address: 127.0.0.1:4000\n')
        previous = self.core.read_bytes(), self.yaml.read_bytes()
        self.write_executable('mv', '''#!/bin/sh
for target in "$@"; do :; done
if [ "$target" = "$TEST_DIR/core" ] && [ ! -f "$TEST_DIR/published-core" ]; then
    /bin/mv "$@" || exit 1
    touch "$TEST_DIR/published-core"
    exec sleep 30
fi
exec /bin/mv "$@"
''')
        owner = self.start('restore', entry.name)
        deadline = time.monotonic() + 5
        while not (self.directory / 'published-core').exists():
            self.assertLess(time.monotonic(), deadline, self.log.read_text() if self.log.exists() else '')
            time.sleep(0.02)
        os.killpg(owner.pid, signal.SIGKILL)
        owner.communicate(timeout=3)
        self.assertEqual(self.core.read_bytes(), (entry / 'core').read_bytes())
        recovered = self.check_new_entry('backed_up', 'backup')
        self.assertEqual((self.core.read_bytes(), self.yaml.read_bytes()), previous)
        self.assert_snapshot(recovered, 'manual', 'v1.2.4', *previous)
        self.assertEqual(list(self.directory.glob('.AdGuardHome.*')), [])
        self.assertEqual(list(self.yaml.parent.glob('.AdGuardHome.*')), [])

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
