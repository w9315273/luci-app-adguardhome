const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const test = require('node:test');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'root/www/luci-static/resources/view/adguardhome/status.js'), 'utf8');
let now = 10000;
const storage = new Map();
let info = { mode: 'dnsmasq-upstream', enabled: true, applied_mode: 'dnsmasq-upstream', applied_enabled: true, redirected: true, busy: false, binpath: '/core' };
let running = true, fail = false, held = null, requests = 0;
function harness() {
 const nodes = [], polls = [];
 const module = new Function('baseclass', 'rpc', 'poll', 'E', '_', 'sessionStorage', 'L', source)(
  { extend: x => x },
  { declare: spec => () => {
    if (spec.method === 'getCoreInfo') return Promise.resolve({ core_exists: true, config_exists: true, version: 'test' });
    if (spec.method === 'getRedirectStatus') {
     requests++;
     return held || (fail ? Promise.reject(Error('offline')) : Promise.resolve({ ...info }));
    }
    return Promise.resolve({ AdGuardHome: { instances: { instance1: { running, command: ['/core'] } } } });
  } },
  { add: (fn, interval) => polls.push({ fn, interval }) },
  (tag, attrs, children) => { const n = { ...attrs, style: {}, textContent: children }; nodes.push(n); return n; },
  x => x,
  { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
  { url: (...parts) => '/cgi-bin/luci/' + parts.join('/') }
 );
 return { page: module.render(), nodes, polls, redirect: () => nodes[2].textContent };
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
test('mode switching, timeout recovery and stale RPC replies', { timeout: 5000 }, async t => {
 const realNow = Date.now;
 Date.now = () => now;
 t.after(() => { Date.now = realNow; });
 let h = harness(); await flush();
 assert.match(h.redirect(), /Run as dnsmasq upstream server/);
 const before = requests;
 now += 1000; await h.polls[0].fn();
 assert.equal(requests, before, 'normal status does not query each second');
 now += 2000; await h.polls[0].fn();
 assert.equal(requests, before + 1);
 h.page.beginSwitch({ mode: 'exchange', enabled: true });
 assert.equal(h.redirect(), 'Switching');
 await h.page.refresh();
 assert.match(h.redirect(), /Switching/, 'old active redirect must not satisfy new mode');
 info.mode = info.applied_mode = 'exchange'; info.busy = true;
 await h.page.refresh();
 assert.match(h.redirect(), /Switching/, 'held mode lock cannot count as success');
 info.busy = false; info.redirected = false;
 await h.page.refresh();
 assert.match(h.redirect(), /Switching/, 'new UCI mode without redirect flag is not active');
 info.redirected = true; running = false;
 await h.page.refresh();
 assert.match(h.redirect(), /Switching/, 'redirect flag alone cannot imply service is running');
 assert.equal(h.nodes[1].textContent, 'NOT RUNNING');
 running = true;
 await h.page.refresh(); assert.match(h.redirect(), /Switching/, 'requires stable samples');
 await h.page.refresh(); assert.match(h.redirect(), /^Use port 53 instead of dnsmasq/);
 assert.equal(storage.size, 0);
 h.page.beginSwitch({ mode: 'redirect', enabled: true });
 now += 31000; fail = true;
 await h.page.refresh(); assert.match(h.redirect(), /Unable to read switch status/);
 assert.equal(h.nodes[1].textContent, 'Status unavailable');
 fail = false;
 h = harness(); await flush(); assert.match(h.redirect(), /not completed/, 'reload preserves pending timeout');
 info.mode = info.applied_mode = 'redirect';
 await h.page.refresh(); await h.page.refresh();
 assert.match(h.redirect(), /^Forward port 53 requests through the firewall/);
 h.page.beginSwitch({ mode: 'none', enabled: true });
 info.mode = info.applied_mode = 'none'; info.redirected = false;
 await h.page.refresh(); await h.page.refresh(); assert.equal(h.redirect(), 'Do not handle DNS');
 h.page.beginSwitch({ mode: 'none', enabled: false });
 info.enabled = info.applied_enabled = false; running = false;
 await h.page.refresh(); await h.page.refresh(); assert.match(h.redirect(), /Disabled/);
 let resolveOld; held = new Promise(resolve => resolveOld = resolve);
 const old = h.page.refresh();
 h.page.beginSwitch({ mode: 'exchange', enabled: true });
 resolveOld({ ...info }); held = null; await old;
 assert.match(h.redirect(), /Switching/, 'in-flight status cannot overwrite new action');
 await h.page.cancelSwitch(); assert.match(h.redirect(), /Disabled/);
 assert.equal(storage.size, 0);

 const baseSource = fs.readFileSync(path.join(root, 'root/www/luci-static/resources/view/adguardhome/base.js'), 'utf8');
 let applied = 0, cancelled = 0, target;
 const base = new Function('view', 'rpc', 'ui', baseSource)(
  { extend: x => x }, { declare: () => () => Promise.resolve({}) },
  { changes: { apply: checked => { assert.equal(checked, true); applied++; } } }
 );
 base.redirectOption = { formvalue: () => 'exchange' };
 base.enabledOption = { formvalue: () => '1' };
 base.sharedStatus = { beginSwitch: value => target = value, cancelSwitch: () => cancelled++ };
 base.handleSave = () => Promise.reject(Error('invalid port'));
 await assert.rejects(base.handleSaveApply(null, '0'), /invalid port/);
 assert.equal(applied, 0); assert.equal(cancelled, 1);
 assert.deepEqual(target, { mode: 'exchange', enabled: true });
 base.handleSave = () => Promise.resolve();
 await base.handleSaveApply(null, '0');
 assert.equal(applied, 1);

 const rpcSource = fs.readFileSync(path.join(root, 'root/usr/share/rpcd/ucode/luci.adguardhome'), 'utf8').replace(/^#!.*\n/, '').replace(/^import .*;\n/gm, '');
 const config = { redirect: 'exchange', enabled: '1', old_redirect: ['exchange'], old_enabled: ['1'], binpath: '/core' };
 let lock = 2;
 const api = new Function('cursor', 'type', 'trim', 'readfile', 'system', 'die', rpcSource)(
  () => ({ get: (pkg, section, name) => config[name], unload() {} }),
  x => Array.isArray(x) ? 'array' : typeof x, x => x.trim(), () => '1', () => lock,
  s => { throw Error(s); }
 )['luci.adguardhome'];
 const result = api.getRedirectStatus.call();
 assert.equal(result.applied_mode, 'exchange'); assert.equal(result.applied_enabled, true); assert.equal(result.busy, true);
 lock = 0; assert.equal(api.getRedirectStatus.call().busy, false);
 lock = 1; assert.throws(() => api.getRedirectStatus.call());
});
