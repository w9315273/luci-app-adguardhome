/* 用模拟的 fs/uci 执行兼容 JavaScript 的 RPC 逻辑.
 * 此处验证日志传输边界, OpenWrt 上的 ucode/LuCI 集成仍需实机验证.
 */
async function runLogTests(rpcSource, viewSource) {
	function check(value, message) {
		if (!value) throw new Error(message);
	}
	var limit = 262144;
	var data = 'a'.repeat(limit * 20) + 'TAIL';
	var inode = 1;
	var readSize = 0;
	var readOffset = -1;
	var closed = false;
	var rpcCode = rpcSource.replace(/^#!.*\n/, '').replace(/^import .*;\n/gm, '');
	var api = new Function('stat', 'open', 'cursor', 'int', 'length', 'die', 'b64enc', rpcCode)(
		function() { return { type: 'file', dev: { major: 0, minor: 1 }, inode: inode, size: data.length }; },
		function() {
			return {
				seek: function(offset) { readOffset = offset; return true; },
				read: function(size) { readSize = size; return data.slice(readOffset, readOffset + size); },
				close: function() { closed = true; }
			};
		},
		function() { return { get: function() { return '/tmp/test.log'; }, unload: function() {} }; },
		Math.trunc, function(s) { return s.length; }, function(s) { throw new Error(s); }, btoa
	)['luci.adguardhome'];
	var backendRead = api.getRuntimeLog.call;
	function read(request) {
		var result = backendRead(request);
		check(typeof result.content_b64 === 'string', 'binary-safe transport present');
		check(!result.content_b64.includes('\0'), 'wire text contains no NUL');
		// 模拟 rpcd 的 C 字符串传输, 检查 NUL 不会截断有效内容.
		result.content = atob(result.content_b64.split('\0')[0]);
		return result;
	}
	var initial = read({ args: { offset: 0, identity: '' } });
	check(readSize === limit && readOffset === data.length - limit && closed, 'bounded tail read');
	check(initial.content.length === limit && initial.content.endsWith('TAIL'), 'latest data returned');
	data += 'APPEND';
	var appended = read({ args: { offset: initial.offset, identity: initial.identity } });
	check(appended.content === 'APPEND' && !appended.reset, 'incremental append');
	data = '';
	var truncated = read({ args: { offset: appended.offset, identity: appended.identity } });
	check(truncated.reset && truncated.offset === 0 && truncated.content === '', 'truncate reset');
	data = 'n'.repeat(appended.offset + 100);
	inode++;
	var rotated = read({ args: { offset: appended.offset, identity: appended.identity } });
	check(rotated.reset && rotated.content.length === limit, 'replacement by larger file resets');
	data += 'x'.repeat(limit * 2);
	var lagged = read({ args: { offset: rotated.offset, identity: rotated.identity } });
	check(lagged.reset && readSize === limit && lagged.content === 'x'.repeat(limit), 'slow reader skips old backlog');

	// 复现清空日志后写入进程仍保留原偏移量的稀疏文件.
	data = '\0'.repeat(120000) + 'visible after clear\n';
	var sparse = read({ args: { offset: 0, identity: '' } });
	check(sparse.offset === data.length, 'cursor includes sparse bytes');
	check(sparse.content.endsWith('visible after clear\n'), 'text after NUL survives rpcd transport');
	var unicodeBytes = new TextEncoder().encode('中文日志正常\n');
	var unicodeBinary = Array.from(unicodeBytes, function(b) { return String.fromCharCode(b); }).join('');
	data += unicodeBinary;
	var unicode = read({ args: { offset: sparse.offset, identity: sparse.identity } });
	check(unicode.offset === data.length && unicode.content === unicodeBinary, 'UTF-8 byte cursor remains correct');

	var pollCallback;
	var nodes = [];
	var response;
	var pending;
	var page = new Function('view', 'rpc', 'poll', 'status', 'E', '_', 'form', 'L', viewSource)(
		{ extend: function(value) { return value; } },
		{ declare: function(spec) {
			return function() {
				if (spec.method === 'clearRuntimeLog') return Promise.resolve({ cleared: true });
				return pending || Promise.resolve(response);
			};
		} },
		{ add: function(callback) { pollCallback = callback; } },
		{ render: function() { return { node: {} }; } },
		function(tag, attrs, children) {
			var node = Object.assign({ tag: tag, children: children, style: {}, events: {},
				addEventListener: function(name, fn) { this.events[name] = fn; } }, attrs);
			nodes.push(node);
			return node;
		},
		function(text) { return text; },
		{ Map: function() {
			this.data = { get: function() { return '0'; } };
			this.section = function() { return { option: function() { return {}; } }; };
			this.render = function() {
				var logFileField = { querySelector: function() { return {}; } };
				var fields = { querySelector: function() { return logFileField; } };
				var card = {
					classList: { add: function() {} },
					querySelector: function() { return fields; },
					insertBefore: function() {}
				};
				return Promise.resolve({ querySelector: function() { return card; } });
			};
		} }, { resource: function(path) { return path; } }
	);
	await page.render(sparse);
	var area = nodes.find(function(n) { return n.tag === 'textarea'; });
	check(area.value.includes('visible after clear') && !area.value.includes('\0'), 'sparse log is visible in page');
	response = unicode;
	await pollCallback();
	check(area.value.includes('中文日志正常'), 'UTF-8 log is decoded for display');
	var clear = nodes.find(function(n) { return n.children === 'dellog'; });
	for (var i = 0; i < 12; i++) {
		response = { enabled: true, content: 'b'.repeat(limit), offset: initial.offset + (i + 1) * limit, identity: initial.identity };
		await pollCallback();
		check(area.value.length <= limit, 'frontend cache stays bounded');
	}
	response = { enabled: true, content: '', offset: 0, identity: initial.identity, reset: true };
	await pollCallback();
	check(area.value === '', 'empty truncated log clears display');
	var resolveOld;
	pending = new Promise(function(resolve) { resolveOld = resolve; });
	var oldPoll = pollCallback();
	clear.events.click();
	await Promise.resolve();
	resolveOld({ enabled: true, content: 'STALE', offset: 5, identity: initial.identity });
	await oldPoll;
	check(area.value === '', 'late poll cannot restore cleared content');
	return 'PASS: binary-safe RPC, sparse log display, UTF-8, bounded reads, rotation and clear/poll race';
}

const test = require('node:test');

test('runtime log transport, bounded reads and clear/poll race', { timeout: 5000 }, async () => {
	const fs = require('fs');
	const path = require('path');
	const root = path.resolve(__dirname, '..');
	await runLogTests(
		fs.readFileSync(path.join(root, 'root/usr/share/rpcd/ucode/luci.adguardhome'), 'utf8'),
		fs.readFileSync(path.join(root, 'root/www/luci-static/resources/view/adguardhome/log.js'), 'utf8')
	);
});
