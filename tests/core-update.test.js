const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setImmediate: nextTurn } = require('node:timers/promises');

async function renderUpdateView(rpc, translate = text => text, options = {}) {
	const source = fs.readFileSync(path.resolve(__dirname,
		'../root/www/luci-static/resources/view/adguardhome/base.js'), 'utf8');
	const card = { classList: { add() {} }, querySelector() {}, appendChild() {} };
	const root = { querySelector: selector => selector === '.cbi-section' ? card : null, insertBefore() {} };
	const form = { Map: class {
		readonly = !!options.readonly;
		section() { return { option: () => ({ value() {}, depends() {} }) }; }
		render() { return Promise.resolve(root); }
	} };
	const nodes = [];
	function element(tag, attrs, children) {
		const node = { tag, ...attrs, textContent: children, style: {},
			addEventListener(event, fn) { this[event] = fn; },
			setAttribute(key, value) { this[key] = value; }
		};
		if (attrs?.type === 'file') {
			node.files = [];
			Object.defineProperty(node, 'value', { set: () => { node.files = []; } });
		}
		if (attrs?.type === 'text')
			node.value = '';
		nodes.push(node);
		return node;
	}
	let poll, modal, notification;
	const ui = {
		showModal: (title, content) => { modal = { title, content }; },
		hideModal: () => { modal = null; },
		addNotification: (_title, content) => { notification = content.textContent; }
	};
	const page = new Function('view', 'form', 'poll', 'rpc', 'status', 'L', 'E', '_', 'ui', 'request', source)(
		{ extend: obj => obj }, form, { add: fn => { poll = fn; } }, rpc,
		{ render: () => ({ node: {}, refresh() {} }) }, { resource: name => name, env: { cgi_base: '/cgi-bin' } },
		element, translate, ui, options.request);
	await page.render({});
	return {
		poll,
		button: nodes.find(node => node.textContent === translate('Update core')),
		force: nodes.find(node => node.textContent === translate('Force update')),
		upload: nodes.find(node => node.textContent === translate('Upload core')),
		install: nodes.find(node => node.textContent === translate('Upload and install')),
		file: nodes.find(node => node.type === 'file'),
		digest: nodes.find(node => node.id === 'agh-upload-sha256'),
		digestError: nodes.find(node => node.id === 'agh-upload-sha256-error'),
		get cancel() { return nodes.findLast(node => node.textContent === translate('Cancel')); },
		get modal() { return modal; },
		get notification() { return notification; },
		message: nodes.find(node => node.tag === 'span' && node.textContent === ''),
		log: nodes.find(node => node.tag === 'textarea'),
		reverse: nodes.find(node => node.type === 'checkbox')
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

test('手动上传先确认文件, 检查传输结果, 并在失败或任务冲突时清理暂存', async () => {
	const calls = [];
	const token = 'Ab12xy';
	const uploadPath = '/tmp/upload-fixture/payload';
	const file = new File(['core fixture'], 'AdGuardHome');
	let state = 'idle', receiptSize = file.size, busy = false;
	const transfer = Promise.withResolvers();
	const rpc = {
		getSessionID: () => 'test-session',
		declare: spec => async (...args) => {
			if (spec.method === 'getCoreUpdate')
				return { state };
			calls.push([spec.method, ...args]);
			switch (spec.method) {
			case 'prepareCoreUpload': return { token, path: uploadPath };
			case 'startCoreUpload':
				assert.deepEqual(spec.params, ['token', 'sha256']);
				state = 'running';
				return busy ? { started: false, reason: 'busy' } : { started: true };
			case 'cancelCoreUpload': return { cancelled: true };
			default: throw new Error(spec.method);
			}
		}
	};
	const request = { post: async (url, form, opts) => {
		assert.equal(url, '/cgi-bin/cgi-upload');
		assert.equal(form.get('sessionid'), 'test-session');
		assert.equal(form.get('filename'), uploadPath);
		assert.equal(form.get('filedata'), file);
		opts.progress({ lengthComputable: true, total: 4, loaded: 1 });
		await transfer.promise;
		return { ok: true, json: () => ({ size: receiptSize }) };
	} };
	const page = await renderUpdateView(rpc, undefined, { request });
	function choose(file) {
		page.file.files = [file];
		page.file.change();
	}
	page.upload.click();
	assert.equal(page.modal.title, 'Upload core');
	for (const invalid of [{ size: 0 }, { size: 128 * 1024 * 1024 + 1 }]) {
		choose(invalid);
		assert.equal(page.install.disabled, true);
		page.install.click();
	}
	choose(file);
	const digest = '19e023d98eb42eb1cdbfd6e4b6ebc937dade59e969506c62eafb3a3d6d2c1e4f';
	for (const invalid of ['a'.repeat(63), '0'.repeat(65), 'g'.repeat(64), 'sha256:', 'sha256:sha256:' + digest, 'sha512:' + digest]) {
		page.digest.value = invalid;
		page.digest.input();
		assert.equal(page.digestError.hidden, false);
		assert.equal(page.install.disabled, true);
		page.install.click();
	}
	page.cancel.click();
	assert.deepEqual(calls, []);
	assert.equal(page.modal, null);
	page.upload.click();
	assert.equal(page.digest.value, '');
	assert.equal(page.digestError.hidden, true);
	assert.equal(page.install.disabled, true);
	choose(file);
	assert.equal(page.install.disabled, false);
	for (const valid of [digest, 'sha256:' + digest, ' SHA256:' + digest.toUpperCase() + ' ']) {
		page.digest.value = valid;
		page.digest.input();
		assert.equal(page.digestError.hidden, true);
		assert.equal(page.install.disabled, false);
	}
	const uploading = page.install.click();
	await nextTurn();
	assert.equal(page.modal, null);
	assert.equal(page.message.textContent, 'Uploading core... 25%');
	assert.ok(page.upload.disabled && page.button.disabled && page.force.disabled);
	await page.poll();
	page.upload.click();
	assert.equal(page.modal, null);
	assert.deepEqual(calls, [['prepareCoreUpload']]);
	transfer.resolve();
	await uploading;
	assert.deepEqual(calls, [['prepareCoreUpload'], ['startCoreUpload', token, digest]]);
	state = 'finished';
	await page.poll();
	assert.equal(page.message.textContent, 'Updated');
	assert.equal(page.upload.disabled, false);

	receiptSize = 0;
	page.upload.click();
	choose(file);
	await page.install.click();
	assert.deepEqual(calls.slice(2), [['prepareCoreUpload'], ['cancelCoreUpload', token]]);
	await page.poll();
	assert.equal(page.message.textContent, 'Unable to upload or install the core.');
	assert.equal(page.upload.disabled, false);

	receiptSize = file.size;
	busy = true;
	page.upload.click();
	choose(file);
	await page.install.click();
	assert.deepEqual(calls.slice(-3), [['prepareCoreUpload'], ['startCoreUpload', token, ''], ['cancelCoreUpload', token]]);
	assert.match(page.notification, /Another core task/);
	assert.equal(page.upload.disabled, true);

	const readonly = await renderUpdateView(rpc, undefined, { readonly: true });
	readonly.upload.click();
	assert.equal(readonly.modal, undefined);
	assert.ok(readonly.upload.disabled);
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
