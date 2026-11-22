const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setImmediate: nextTurn } = require('node:timers/promises');

test('核心更新区分最新版本, 成功与启动失败, 忽略点击前的状态响应', async () => {
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
	let poll, reply;
	const requests = [];
	const start = Promise.withResolvers();
	const rpc = { declare: spec => spec.method === 'startCoreUpdate' ? force => {
		requests.push(force);
		return start.promise;
	} : () => Promise.resolve(reply) };
	const page = new Function('view', 'form', 'poll', 'rpc', 'status', 'L', 'E', '_', source)(
		{ extend: obj => obj }, form, { add: fn => { poll = fn; } }, rpc,
		{ render: () => ({ node: {}, refresh() {} }) }, { resource: name => name }, element, text => text);
	await page.render({});
	const button = nodes.find(node => node.textContent === 'Update core version');
	const force = nodes.find(node => node.textContent === 'Force update');
	const message = nodes.find(node => node.tag === 'span' && node.textContent === '');
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
		reply = { state };
		await poll();
		assert.equal(message.textContent, label);
		assert.equal(force.disabled, false);
	}
	assert.deepEqual(requests, [false, true, true, true]);
});
