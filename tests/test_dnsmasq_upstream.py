"""用隔离的 UCI 模拟器执行真实启动脚本, 不修改路由器配置."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DNS = 'dhcp.@dnsmasq[0].'
BACKUP = 'AdGuardHome.dnsmasq_backup'


class DnsmasqUpstreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='agh-dns-test-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.state_file = self.path / 'uci.json'
        self.env = dict(os.environ, UCI_STATE=str(self.state_file),
                        TEST_DIR=str(self.path), PATH=str(self.path) + ':/usr/bin:/bin')
        stub = self.path / 'uci'
        stub.write_text('''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
p=Path(os.environ['UCI_STATE']); state=json.loads(p.read_text())
args=[x for x in sys.argv[1:] if x != '-q']; op=args[0]
arg=args[1] if len(args)>1 else ''
key,_,value=arg.partition('=')
key=key.replace('AdGuardHome.@AdGuardHome[0]', 'AdGuardHome.AdGuardHome')
if op=='export':
 print(json.dumps({k:v for k,v in state.items() if k.startswith(key+'.')}, sort_keys=True)); sys.exit(0)
if op=='get':
 if key not in state: sys.exit(1)
 print(' '.join(state[key]) if isinstance(state[key],list) else state[key])
 sys.exit(0)
if op=='set': state[key]=value
elif op=='delete':
 matched=[k for k in state if k==key or k.startswith(key+'.')]
 if not matched: sys.exit(1)
 for k in matched: del state[k]
elif op=='add_list':
 if key not in state: state[key]=[]
 if not isinstance(state[key],list): state[key]=[state[key]]
 state[key].append(value)
elif op=='del_list':
 if key not in state: sys.exit(1)
 state[key]=[x for x in state[key] if x!=value]
 if not state[key]: del state[key]
elif op=='commit':
 if os.environ.get('FAIL_COMMIT')==key: sys.exit(1)
elif op=='revert':
 for k in list(state):
  if k==key or k.startswith(key+'.'): del state[k]
else: sys.exit('unsupported UCI operation: '+op)
p.write_text(json.dumps(state))
''')
        stub.chmod(0o755)
        source = (ROOT / 'root/etc/init.d/AdGuardHome').read_text()
        begin = source.index('save_dnsmasq_upstream_config()')
        end = source.index('\ndo_redirect() {\n', source.index('_do_redirect()'))
        self.functions = source[begin:end]
        self.functions = self.functions.replace('/etc/init.d/dnsmasq restart', 'restart_dnsmasq')
        self.functions = self.functions.replace('/var/run/AdGredir', str(self.path / 'redirect_flag'))
        self.functions = self.functions.replace('/var/lock/AdGuardHome-redirect.lock', str(self.path / 'redirect.lock'))
        self.functions += '''
restart_dnsmasq() { echo restart >> "$TEST_DIR/restarts"; [ "$FAIL_RESTART" != 1 ]; }
logger() { :; }
config_get() {
    local value
    value="$(uci -q get "AdGuardHome.$2.$3")" || value="$4"
    export "$1=$value"
}
config_editor() { echo "$DNS_PORT"; }
CONFIGURATION=AdGuardHome
'''

    def seed(self, **options):
        self.state_file.write_text(json.dumps({DNS+k: v for k, v in options.items()}))

    def state(self):
        return json.loads(self.state_file.read_text())

    def dns(self):
        return {k[len(DNS):]: v for k, v in self.state().items() if k.startswith(DNS)}

    def run_shell(self, command, expected=0, **env):
        result = subprocess.run(['sh', '-c', self.functions + '\n' + command],
                                env=dict(self.env, **env), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)

    def test_round_trip_preserves_servers_and_custom_options(self):
        original = dict(server=['9.9.9.9', '/internal/192.168.1.2', '127.0.0.1#17450'],
                        resolvfile='/etc/custom resolver.conf', noresolv='0', port='53')
        self.seed(**original)
        self.run_shell('set_forward_dnsmasq 1745')
        self.assertEqual(self.dns()['server'], ['127.0.0.1#1745', '/internal/192.168.1.2'])
        self.assertEqual(self.dns()['resolvfile'], original['resolvfile'])
        self.assertEqual(self.dns()['noresolv'], '1')
        self.run_shell('stop_forward_dnsmasq 1745')
        self.assertEqual(self.dns(), original)
        self.assertNotIn(BACKUP, self.state())

    def test_absent_options_stay_absent(self):
        self.seed(port='53')
        self.run_shell('set_forward_dnsmasq 1745; stop_forward_dnsmasq 1745')
        self.assertEqual(self.dns(), {'port': '53'})

    def test_explicit_empty_and_noresolv_one_preserved(self):
        original = dict(resolvfile='', noresolv='1', server=['1.1.1.1'])
        self.seed(**original)
        self.run_shell('set_forward_dnsmasq 1745; stop_forward_dnsmasq 1745')
        self.assertEqual(self.dns(), original)

    def test_repeated_start_and_port_change_do_not_replace_snapshot(self):
        original = dict(server=['8.8.8.8'], noresolv='0')
        self.seed(**original)
        self.run_shell('set_forward_dnsmasq 1745')
        snapshot = {k:v for k,v in self.state().items() if k.startswith(BACKUP)}
        self.run_shell('set_forward_dnsmasq 1745; set_forward_dnsmasq 5353')
        self.assertEqual({k:v for k,v in self.state().items() if k.startswith(BACKUP)}, snapshot)
        self.assertEqual(self.dns()['server'], ['127.0.0.1#5353'])
        self.assertEqual(len((self.path / 'restarts').read_text().splitlines()), 2)
        self.run_shell('stop_forward_dnsmasq 5353; stop_forward_dnsmasq 5353')
        self.assertEqual(self.dns(), original)

    def test_domain_rules_kept_but_catch_all_removed(self):
        servers = ['/#/1.1.1.1', '/example/#/8.8.8.8', '9.9.9.9',
                   '/internal/192.168.1.2', '/*.test/192.168.1.3', '//192.168.1.4', '/lan/']
        self.seed(server=servers)
        self.run_shell('set_forward_dnsmasq 1745')
        self.assertEqual(self.dns()['server'], ['127.0.0.1#1745'] + servers[3:])
        self.run_shell('stop_forward_dnsmasq 1745')
        self.assertEqual(self.dns()['server'], servers)

    def test_legacy_endpoint_removed_in_any_position_without_prefix_match(self):
        self.seed(server=['9.9.9.9', '127.0.0.1#17450', '127.0.0.1#1745'], noresolv='1')
        self.run_shell('stop_forward_dnsmasq 1745')
        self.assertEqual(self.dns()['server'], ['9.9.9.9', '127.0.0.1#17450'])
        self.run_shell('stop_forward_dnsmasq 1745')
        self.assertEqual(self.dns()['server'], ['9.9.9.9', '127.0.0.1#17450'])

    def test_legacy_upgrade_does_not_save_old_plugin_endpoint(self):
        self.seed(server=['/internal/192.168.1.2', '127.0.0.1#1745'], noresolv='1')
        self.run_shell('set_forward_dnsmasq 1745 dnsmasq-upstream 1 1745')
        self.assertEqual(self.state()[BACKUP+'.server'], ['/internal/192.168.1.2'])
        self.run_shell('stop_forward_dnsmasq 1745')
        self.assertEqual(self.dns()['server'], ['/internal/192.168.1.2'])
        self.assertNotIn('noresolv', self.dns())
        self.assertIn('resolvfile', self.dns())

    def test_snapshot_commit_failure_does_not_change_dns(self):
        original = dict(server=['9.9.9.9'], noresolv='0')
        self.seed(**original)
        self.run_shell('set_forward_dnsmasq 1745', expected=1, FAIL_COMMIT='AdGuardHome')
        self.assertEqual(self.dns(), original)
        self.assertFalse((self.path / 'restarts').exists())

    def test_restore_restart_failure_keeps_snapshot_for_retry(self):
        self.seed(server=['9.9.9.9'])
        self.run_shell('set_forward_dnsmasq 1745')
        self.run_shell('stop_forward_dnsmasq 1745', expected=1, FAIL_RESTART='1')
        self.assertEqual(self.state()[BACKUP+'.ready'], '1')
        self.run_shell('stop_forward_dnsmasq 1745')
        self.assertNotIn(BACKUP, self.state())
        self.assertEqual(self.dns(), {'server': ['9.9.9.9']})

    def test_mode_switch_and_disable_through_redirect_dispatcher(self):
        self.seed(server=['9.9.9.9'], noresolv='0', port='53')
        self.run_shell('uci set AdGuardHome.AdGuardHome.redirect=dnsmasq-upstream; _do_redirect 1', DNS_PORT='1745')
        self.assertEqual(self.dns()['server'], ['127.0.0.1#1745'])
        self.run_shell('_do_redirect 1', DNS_PORT='5353')
        self.assertEqual(self.dns()['server'], ['127.0.0.1#5353'])
        self.run_shell('uci set AdGuardHome.AdGuardHome.redirect=none; _do_redirect 1', DNS_PORT='5353')
        self.assertEqual(self.dns(), {'server':['9.9.9.9'], 'noresolv':'0', 'port':'53'})
        self.run_shell('uci set AdGuardHome.AdGuardHome.redirect=dnsmasq-upstream; _do_redirect 1', DNS_PORT='1745')
        self.run_shell('_do_redirect 0', expected=1, DNS_PORT='1745')
        self.assertEqual(self.dns(), {'server':['9.9.9.9'], 'noresolv':'0', 'port':'53'})

    def test_dispatcher_preserves_preexisting_matching_endpoint(self):
        original = {'server': ['127.0.0.1#1745', '9.9.9.9'], 'port': '53'}
        self.seed(**original)
        self.run_shell('uci set AdGuardHome.AdGuardHome.redirect=dnsmasq-upstream; _do_redirect 1', DNS_PORT='1745')
        self.run_shell('_do_redirect 1', DNS_PORT='5353')
        self.assertEqual(self.state()[BACKUP+'.server'], original['server'])
        self.run_shell('_do_redirect 0', expected=1, DNS_PORT='5353')
        self.assertEqual(self.dns(), original)
        self.run_shell('uci set AdGuardHome.AdGuardHome.redirect=none; _do_redirect 0', expected=1, DNS_PORT='5353')
        self.assertEqual(self.dns(), original)

    def test_overlapping_starts_keep_original_snapshot(self):
        self.seed(server=['9.9.9.9'], port='53')
        self.run_shell('uci set AdGuardHome.AdGuardHome.redirect=dnsmasq-upstream; _do_redirect 1 & first=$!; _do_redirect 1 & second=$!; wait "$first" && wait "$second"', DNS_PORT='1745')
        self.assertEqual(self.state()[BACKUP+'.server'], ['9.9.9.9'])
        self.assertEqual(self.dns()['server'], ['127.0.0.1#1745'])
        self.run_shell('_do_redirect 0', expected=1, DNS_PORT='1745')
        self.assertEqual(self.dns(), {'server': ['9.9.9.9'], 'port': '53'})


if __name__ == '__main__':
    unittest.main()
