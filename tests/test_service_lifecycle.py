"""通过端口占用模拟器执行真实启动脚本, 验证服务交接顺序."""
import subprocess
import unittest
import test_dnsmasq_upstream as dns


class ServiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.h = dns.DnsmasqUpstreamTests('runTest')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.path = self.h.path
        source = (dns.ROOT / 'root/etc/init.d/AdGuardHome').read_text()
        lifecycle = source[source.index('start_service() {'):source.index('\nboot() {')]
        lifecycle = lifecycle.replace('/var/run/', str(self.path) + '/')
        lifecycle = lifecycle.replace('/lib/upgrade/keep.d/luci-app-adguardhome', str(self.path / 'keep'))
        lifecycle = lifecycle.replace('/usr/share/AdGuardHome/web_host.sh',
                                      str(dns.ROOT / 'root/usr/share/AdGuardHome/web_host.sh'))
        self.h.functions += '\n' + lifecycle + '''
config_load() { :; }
config_get_bool() { config_get "$@"; }
config_editor() {
    if [ -n "$4" ]; then cat "$TEST_DIR/yaml-port"; return; fi
    [ ! -f "$TEST_DIR/live-port" ] || { echo 'editing live config' >&2; return 1; }
    printf '%s' "$2" > "$TEST_DIR/yaml-port"
    echo "yaml:$2" >> "$TEST_DIR/events"
}
stop_core() {
    [ "$FAIL_STOP" != 1 ] || return 1
    if [ -f "$TEST_DIR/live-port" ]; then
        # 模拟核心正常退出时将内存中的配置写回文件.
        cat "$TEST_DIR/live-port" > "$TEST_DIR/yaml-port"
        rm "$TEST_DIR/live-port"
        echo stopped >> "$TEST_DIR/events"
    fi
}
restart_dnsmasq() {
    local port="$(uci -q get dhcp.@dnsmasq[0].port)"
    if [ -f "$TEST_DIR/live-port" ] && [ "$(cat "$TEST_DIR/live-port")" = "$port" ]; then
        echo 'Address in use' >&2
        return 1
    fi
    echo "dnsmasq:$port" >> "$TEST_DIR/events"
    [ "$FAIL_RESTART" != 1 ]
}
get_filesystem() { echo tmpfs; }
get_tz() { SET_TZ=''; }
procd_open_instance() { :; }
procd_set_param() {
    if [ "$1" = command ]; then shift; printf '%s\n' "$@" > "$TEST_DIR/command"; fi
}
procd_close_instance() {
    local port="$(cat "$TEST_DIR/yaml-port")"
    [ "$port" != "$(uci -q get dhcp.@dnsmasq[0].port)" ] || return 1
    printf '%s' "$port" > "$TEST_DIR/live-port"
    echo "started:$port" >> "$TEST_DIR/events"
}
ubus() { echo "ubus:$3" >> "$TEST_DIR/events"; }
start() { start_service; }
'''
        core = self.path / 'core'
        core.write_text('#!/bin/sh\necho "  -p, --port VALUE"\n')
        core.chmod(0o755)
        (self.path / 'config.yaml').touch()
        (self.path / 'yaml-port').write_text('3053')
        self.h.seed(server=['9.9.9.9'], noresolv='0', port='53')
        self.h.run_shell('''
uci set AdGuardHome.AdGuardHome.enabled=1
uci set AdGuardHome.AdGuardHome.configpath="$TEST_DIR/config.yaml"
uci set AdGuardHome.AdGuardHome.binpath="$TEST_DIR/core"
uci set AdGuardHome.AdGuardHome.workdir="$TEST_DIR/work"
uci set AdGuardHome.AdGuardHome.redirect=dnsmasq-upstream
_do_redirect 1 0
''')
        (self.path / 'live-port').write_text('3053')
        (self.path / 'events').write_text('')

    def events(self):
        return (self.path / 'events').read_text().splitlines()

    def test_web_port_preserves_yaml_bind_address_and_paths(self):
        config = self.path / 'config with spaces.yaml'
        core = self.path / 'core'
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.httpport=3333; '
                         'uci set AdGuardHome.AdGuardHome.configpath="$TEST_DIR/config with spaces.yaml"; '
                         'uci set AdGuardHome.AdGuardHome.logfile="$TEST_DIR/log with spaces"')
        config.write_text('bind_host: 127.0.0.1\n')
        self.h.run_shell('start_service')
        self.assertIn('-p', (self.path / 'command').read_text().splitlines())
        core.write_text('''#!/bin/sh
case "$1" in
    --help) echo "  --web-addr VALUE";;
    --check-config)
        [ "$3" = "$5/config.yaml" ] && [ "$3" != "$TEST_DIR/config with spaces.yaml" ] || exit 1
        cp "$3" "$TEST_DIR/probe-input" && cp "$TEST_DIR/normalized" "$3";;
    *) exit 1;;
esac
''')
        normalized = self.path / 'normalized'
        probe_input = self.path / 'probe-input'
        for content, canonical, host in [
            (None, None, '0.0.0.0'),
            ('http: {pprof: {port: 6060}}', 'http:\n    pprof:\n      port: 6060', '0.0.0.0'),
            ('http:\n  pprof:\n    port: 6060\n  address: 127.0.0.1:3000', None, '127.0.0.1'),
            ('# 管理页\r\nhttp:\r\n  address: "[::1]:8080" # local\r\n', None, '[::1]'),
            ('http:\n extra:\n  address: 0.0.0.0:6060\n address: 127.0.0.1:3000',
             'http:\n    address: 127.0.0.1:3000\n    extra:\n      address: 0.0.0.0:6060', '127.0.0.1'),
            ('addr: &addr "[fe80::1%eth0]:8080"\nhttp: {address: *addr}',
             'addr: \'[fe80::1%eth0]:8080\'\n  http:\n    address: \'[fe80::1%eth0]:8080\'', '[fe80::1%eth0]'),
            ('bind_host: "::1"', 'bind_host: ::1', '[::1]'),
        ]:
            with self.subTest(content=content):
                probe_input.unlink(missing_ok=True)
                normalized.unlink(missing_ok=True)
                if canonical is not None:
                    normalized.write_text('schema_version: 35\nsource:\n  ' + canonical + '\n')
                if content is None:
                    config.unlink()
                else:
                    config.write_text(content)
                self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=none; start_service')
                self.assertEqual((self.path / 'command').read_text().splitlines(),
                                 [str(core), '-c', str(config), '-w', str(self.path / 'work'),
                                  '--web-addr', host + ':3333', '-l', str(self.path / 'log with spaces')])
                if canonical is not None:
                    self.assertEqual(probe_input.read_text(), '---\nsource:\n' +
                                     ''.join('  ' + line + '\n' for line in content.splitlines()))
                else:
                    self.assertFalse(probe_input.exists())
        config.write_text('http: {address: invalid}')
        normalized.write_text('schema_version: 35\nsource:\n  http:\n    address: invalid\n')
        (self.path / 'command').unlink()
        self.h.run_shell('start_service', expected=1)
        self.assertFalse((self.path / 'command').exists())

        relative = 'relative config.yaml'
        (self.path / 'work' / relative).write_text('http:\n  address: 192.0.2.3:3000\n')
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.configpath="relative config.yaml"; start_service')
        self.assertEqual((self.path / 'command').read_text().splitlines(),
                         [str(core), '-c', relative, '-w', str(self.path / 'work'),
                          '--web-addr', '192.0.2.3:3333', '-l', str(self.path / 'log with spaces')])

    def exchange(self):
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=exchange; reload_service')
        self.assertEqual((self.path / 'live-port').read_text(), '53')
        self.assertEqual(self.h.dns()['port'], '3053')

    def test_upstream_to_exchange_releases_both_ports_before_start(self):
        self.exchange()
        events = self.events()
        self.assertLess(events.index('stopped'), events.index('yaml:53'))
        self.assertLess(events.index('yaml:53'), events.index('dnsmasq:3053'))
        self.assertLess(events.index('dnsmasq:3053'), events.index('started:53'))
        self.assertNotIn('ubus:event', events)
        self.assertEqual(sum(e.startswith('dnsmasq:') for e in events), 1)

    def test_exchange_to_upstream_releases_53_before_dnsmasq(self):
        self.exchange()
        (self.path / 'events').write_text('')
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=dnsmasq-upstream; reload_service')
        events = self.events()
        self.assertLess(events.index('stopped'), events.index('dnsmasq:53'))
        self.assertLess(events.index('dnsmasq:53'), events.index('started:3053'))
        self.assertEqual(self.h.dns()['server'], ['127.0.0.1#3053'])
        self.assertNotIn('ubus:event', events)
        self.assertEqual(sum(e.startswith('dnsmasq:') for e in events), 1)

    def test_stopping_exchange_does_not_schedule_another_start(self):
        self.exchange()
        (self.path / 'events').write_text('')
        self.h.run_shell('stop_service')
        self.assertFalse((self.path / 'live-port').exists())
        self.assertEqual(self.h.dns()['port'], '53')
        self.assertNotIn('ubus:event', self.events())

    def test_failed_stop_does_not_modify_ports(self):
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=exchange; reload_service',
                         expected=1, FAIL_STOP='1')
        self.assertEqual((self.path / 'yaml-port').read_text(), '3053')
        self.assertEqual(self.h.dns()['port'], '53')
        self.assertEqual(self.events(), [])

    def test_failed_dnsmasq_restart_does_not_launch_core(self):
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=exchange; reload_service',
                         expected=1, FAIL_RESTART='1')
        self.assertFalse((self.path / 'live-port').exists())
        self.assertFalse(any(x.startswith('started:') for x in self.events()))

    def test_crashed_core_is_started_with_prepared_ports(self):
        self.exchange()
        (self.path / 'live-port').unlink()
        (self.path / 'events').write_text('')
        self.h.run_shell('reload_service')
        self.assertEqual((self.path / 'live-port').read_text(), '53')
        self.assertEqual(self.events(), ['started:53'])

    def test_retry_after_committed_port_but_failed_handoff(self):
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=exchange; reload_service',
                         expected=1, FAIL_RESTART='1')
        self.assertEqual(self.h.dns()['port'], '3053')
        self.assertEqual((self.path / 'yaml-port').read_text(), '53')
        self.assertEqual(self.h.state().get(dns.BACKUP + '.ready'), '1')
        (self.path / 'events').write_text('')
        self.h.run_shell('reload_service')
        self.assertEqual(self.events(), ['dnsmasq:3053', 'started:53'])
        self.assertNotIn(dns.BACKUP, self.h.state())


    def test_config_watcher_queues_reload_only_after_dnsmasq_handoff(self):
        self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=exchange; _do_redirect 1')
        events = self.events()
        self.assertLess(events.index('dnsmasq:3053'), events.index('ubus:event'))
        self.assertEqual(sum(e.startswith('dnsmasq:') for e in events), 1)

    def test_repeated_round_trips_keep_ports_and_original_upstreams(self):
        for _ in range(3):
            self.exchange()
            self.h.run_shell('uci set AdGuardHome.AdGuardHome.redirect=dnsmasq-upstream; reload_service')
            self.assertEqual((self.path / 'live-port').read_text(), '3053')
            self.assertEqual(self.h.dns()['port'], '53')
            self.assertEqual(self.h.dns()['server'], ['127.0.0.1#3053'])
        self.h.run_shell('stop_service')
        self.assertEqual(self.h.dns()['server'], ['9.9.9.9'])



class ProcessHandoffTests(unittest.TestCase):
    def test_stop_wait_start_does_not_reuse_a_live_jail(self):
        source = (dns.ROOT / 'root/etc/init.d/AdGuardHome').read_text()
        helpers = source[source.index('restart_dnsmasq()'):source.index('save_dnsmasq_upstream_config()')]
        helpers = helpers.replace('/etc/init.d/dnsmasq', 'dnsmasq_command')
        script = helpers + """
ubus() { echo '{}'; }
jsonfilter() { cat >/dev/null; echo 1234; }
old_jail=1
dnsmasq_command() {
    echo "$1"
    if [ "$1" = start ]; then [ "$old_jail" = 0 ] || return 1; fi
}
wait_for_pid_exit() { echo "wait:$1"; old_jail=0; }
wait_for_dns_port_release() { echo "port:$1"; }
restart_dnsmasq 53
"""
        result = subprocess.run(['busybox', 'ash', '-c', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['stop', 'wait:1234', 'port:53', 'start', 'port:53'])

    def test_failed_jail_stop_does_not_register_a_replacement(self):
        source = (dns.ROOT / 'root/etc/init.d/AdGuardHome').read_text()
        helpers = source[source.index('restart_dnsmasq()'):source.index('save_dnsmasq_upstream_config()')]
        helpers = helpers.replace('/etc/init.d/dnsmasq', 'dnsmasq_command')
        script = helpers + """
ubus() { echo '{}'; }
jsonfilter() { cat >/dev/null; echo 1234; }
dnsmasq_command() { echo "$1"; }
wait_for_pid_exit() { return 1; }
logger() { :; }
restart_dnsmasq 53
"""
        result = subprocess.run(['busybox', 'ash', '-c', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['stop'])

    def test_actual_dns_socket_handoff(self):
        import socket
        import threading
        source = (dns.ROOT / 'root/etc/init.d/AdGuardHome').read_text()
        helper = source[source.index('wait_for_dns_port_release()'):source.index('restart_dnsmasq()')]
        for family in [socket.AF_INET, socket.AF_INET6]:
            for kind in [socket.SOCK_STREAM, socket.SOCK_DGRAM]:
                with self.subTest(family=family, kind=kind):
                    sock = socket.socket(family, kind)
                    self.addCleanup(sock.close)
                    try:
                        sock.bind(('127.0.0.1' if family == socket.AF_INET else '::1', 0))
                    except OSError:
                        if family == socket.AF_INET6:
                            continue
                        raise
                    if kind == socket.SOCK_STREAM:
                        sock.listen()
                    port = sock.getsockname()[1]
                    blocked = subprocess.run(['sh', '-c', helper + f'\nsleep() {{ :; }}\nwait_for_dns_port_release {port}'], capture_output=True, text=True, timeout=10)
                    self.assertEqual(blocked.returncode, 1, blocked.stderr)
                    timer = threading.Timer(0.2, sock.close)
                    timer.start()
                    released = subprocess.run(['sh', '-c', helper + f'\nwait_for_dns_port_release {port}'], capture_output=True, text=True, timeout=5)
                    timer.join()
                    self.assertEqual(released.returncode, 0, released.stderr)

    def test_stop_core_deletes_crashed_instance_without_pid(self):
        source = (dns.ROOT / 'root/etc/init.d/AdGuardHome').read_text()
        helpers = source[source.index('wait_for_pid_exit()'):source.index('save_dnsmasq_upstream_config()')]
        core = source[source.index('stop_core()'):source.index('\nagh_reload()')]
        script = helpers + core + '''
ubus() { [ "$2" = list ] && echo '{}' || echo deleted >&2; }
jsonfilter() { cat >/dev/null; case "$2" in *.instance1) echo '{"running":false}';; esac; }
stop_core
'''
        result = subprocess.run(['sh','-c',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('deleted',result.stderr)


if __name__ == '__main__':
    unittest.main()
