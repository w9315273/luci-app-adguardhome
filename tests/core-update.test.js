const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setImmediate: nextTurn } = require('node:timers/promises');

async function renderUpdateView(rpc, translate = text => text) {
	const source = fs.readFileSync(path.resolve(__dirname,
		'../root/www/luci-static/resources/view/adguardhome/base.js'), 'utf8');
	const card = { classList: { add() {} }, querySelector() {}, appendChild() {} };
	const root = { querySelector: selector => selector === '.cbi-section' ? card : null, insertBefore() {} };
	const form = { Map: class {
		section() { return { option: () => ({ value() {}, depends() {} }) }; }
		render() { return Promise.resolve(root); }
	} };
	const nodes = [];
	function element(tag, attrs, children) {
		const node = { tag, textContent: children, style: {}, addEventListener(event, fn) { this[event] = fn; } };
		nodes.push(node);
		return node;
	}
	let poll;
	const page = new Function('view', 'form', 'poll', 'rpc', 'status', 'L', 'E', '_', source)(
		{ extend: obj => obj }, form, { add: fn => { poll = fn; } }, rpc,
		{ render: () => ({ node: {}, refresh() {} }) }, { resource: name => name }, element, translate);
	await page.render({});
	return {
		poll,
		button: nodes.find(node => node.textContent === translate('Update core version')),
		force: nodes.find(node => node.textContent === translate('Force update')),
		message: nodes.find(node => node.tag === 'span' && node.textContent === ''),
		log: nodes.find(node => node.tag === 'textarea'),
		reverse: nodes.find(node => node.tag === 'input' && node.change)
	};
}

test('核心更新区分最新版本, 成功与启动失败, 忽略点击前的状态响应', async () => {
	let reply;
	const requests = [];
	const start = Promise.withResolvers();
	const rpc = { declare: spec => spec.method === 'startCoreUpdate' ? force => {
		requests.push(force);
		return start.promise;
	} : () => Promise.resolve(reply) };
	const { button, force, message, log, poll } = await renderUpdateView(rpc);
	const stale = Promise.withResolvers();
	reply = stale.promise;
	const previousPoll = poll();
	button.click();
	stale.resolve({ state: 'finished' });
	await previousPoll;
	assert.equal(message.textContent, 'Check...');
	assert.equal(button.disabled, true);

	reply = { state: 'current' };
	start.resolve({ started: true });
	await nextTurn();
	assert.equal(message.textContent, 'Already up to date');
	assert.equal(button.disabled, false);
	for (const [state, label] of [['finished', 'Updated'], ['start_failed', 'Core installed, service failed to start'],
		['failure', 'Update failed']]) {
		reply = { state: 'running' };
		force.click();
		await nextTurn();
		assert.equal(force.disabled, true);
		assert.equal(message.textContent, '');
		reply = { state };
		await poll();
		assert.equal(message.textContent, label);
		assert.equal(force.disabled, false);
	}
	assert.deepEqual(requests, [false, true, true, true]);
	for (const state of ['backed_up', 'restored', 'deleted']) {
		reply = { state: 'running' };
		await poll();
		reply = { state, log: 'Operation log' };
		await poll();
		assert.equal(message.textContent, '');
		assert.equal(force.disabled, false);
		assert.equal(log.value, reply.log);
	}
});

test('不同语言的 LuCI 页面读取同一后台任务时按各自语言显示日志和逆序', async () => {
	const po = fs.readFileSync(path.resolve(__dirname, '../po/zh-cn/AdGuardHome.po'), 'utf8');
	const entries = po.matchAll(/^(?:msgctxt (".*")\n)?msgid (".*")\nmsgstr (".*")$/gm);
	const translations = new Map(Array.from(entries, ([, context, id, text]) => [
		JSON.stringify([context ? JSON.parse(context) : '', JSON.parse(id)]), JSON.parse(text)
	]));
	function gettext(text, context = '') {
		return translations.get(JSON.stringify([context, text])) || text;
	}
	const executable = '/mnt/core data: nightly/AdGuardHome';
	const url = 'https://example.org:8443/releases/arm64?name=unknown';
	const diagnostic = 'uclient-fetch: Connection error: Connection timed out';
	const lines = [
		'Checking for core updates...',
		'',
		'Executable path: ' + executable,
		'Current AdGuard Home version: unknown',
		'Download URL: ' + url,
		'YAML validation skipped: no core is installed.',
		'YAML configuration validation failed.',
		diagnostic,
		'Connection error: Connection timed out',
		''
	];
	const reply = { state: 'running', log: lines.join('\n') };
	const rpc = { declare: spec => () => {
		assert.equal(spec.method, 'getCoreUpdate');
		return Promise.resolve(reply);
	} };

	const english = await renderUpdateView(rpc);
	const chinese = await renderUpdateView(rpc, gettext);
	await Promise.all([english.poll(), chinese.poll()]);
	assert.equal(english.log.value, reply.log);
	const translated = [
		'开始检查更新, 请耐心等待 ...',
		'',
		'执行文件路径: ' + executable,
		'当前 AdGuardHome 版本: 未知',
		'下载链接: ' + url,
		'未安装核心, 已跳过 YAML 配置校验.',
		'YAML 配置校验失败.',
		diagnostic,
		'Connection error: Connection timed out',
		''
	];
	assert.equal(chinese.log.value, translated.join('\n'));

	chinese.reverse.checked = true;
	chinese.reverse.change();
	assert.deepEqual(chinese.log.value.split('\n'), translated.slice().reverse());
	assert.equal(english.log.value, lines.join('\n'));
});
