const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

test('rpcd 定时回收中断的上传和解压文件, 保留活跃任务与其他目录', t => {
	const work = fs.mkdtempSync(path.join(os.tmpdir(), 'agh-sweep-'));
	t.after(() => fs.rmSync(work, {recursive: true, force: true}));
	const root = path.join(work, 'uploads');
	fs.mkdirSync(root, {mode: 0o700});
	const source = fs.readFileSync(path.join(__dirname, '../root/usr/share/rpcd/ucode/luci.adguardhome'), 'utf8')
		.replace(/^#!.*\n/, '').replace(/^import .*;\n/gm, '').replace("'/var/run/AdGuardHome-uploads'", JSON.stringify(root));
	let receiving = true, pinned = true, tick;
	function slot(name, stageId) {
		const dir = path.join(root, name);
		fs.mkdirSync(dir, {mode: 0o700});
		fs.writeFileSync(path.join(dir, 'payload'), 'archive');
		if (stageId) {
			const stage = path.join(work, '.AdGuardHome.' + stageId);
			fs.mkdirSync(stage, {mode: 0o700});
			fs.symlinkSync(stage, path.join(dir, '.stage'));
			fs.writeFileSync(path.join(stage, '.upload-owner'), dir + '\n');
			fs.writeFileSync(path.join(stage, 'upload'), 'archive');
			fs.writeFileSync(path.join(stage, 'core'), 'binary');
		}
		fs.utimesSync(dir, 1, 1);
		return dir;
	}
	const pending = slot('OLD123'), fresh = slot('FRESH1');
	fs.utimesSync(fresh, 999, 999);
	const orphan = slot('ready.ORPHAN', 'ORPHAN'), active = slot('ready.ACTIVE', 'ACTIVE');
	const orphanStage = fs.readlinkSync(path.join(orphan, '.stage'));
	const activeStage = fs.readlinkSync(path.join(active, '.stage'));
	const foreign = slot('ready.OTHER1', 'OTHER1');
	const foreignStage = fs.readlinkSync(path.join(foreign, '.stage'));
	fs.writeFileSync(path.join(foreignStage, '.upload-owner'), 'another task\n');
	const extra = slot('ready.OTHER2', 'OTHER2');
	const extraStage = fs.readlinkSync(path.join(extra, '.stage'));
	fs.writeFileSync(path.join(extraStage, 'user-data'), 'keep');
	const unrecognized = slot('other');

	function stat(dir) {
		const s = fs.lstatSync(dir, {throwIfNoEntry: false});
		return s && {type: s.isDirectory() ? 'directory' : s.isFile() ? 'file' : 'link',
			uid: 0, mode: s.mode & 0o777, mtime: s.mtimeMs / 1000};
	}
	function unlink(file) {
		if (!fs.lstatSync(file, {throwIfNoEntry: false})) return false;
		fs.unlinkSync(file);
		return true;
	}
	new Function('timer', 'lstat', 'time', 'lsdir', 'match', 'length', 'system', 'open', 'unlink', 'rmdir',
		'readlink', 'substr', 'basename', 'readfile', source)(
		(delay, fn) => { assert.equal(delay, 60000); tick = fn; }, stat, () => 1000,
		// ucode 的数组遍历返回每个名称, 此处用同名键模拟.
		dir => Object.fromEntries(fs.readdirSync(dir).map(s => [s, s])),
		(s, re) => s.match(re), s => s.length, () => receiving ? 0 : 1,
		dir => ({lock: mode => { assert.equal(mode, 'xn'); return !(pinned && dir === active); }, close() {}}),
		unlink, dir => { fs.rmdirSync(dir); return true; },
		file => stat(file)?.type === 'link' ? fs.readlinkSync(file) : null, (s, start, len) => s.slice(start, start + len),
		path.basename, file => fs.readFileSync(file, 'utf8')
	);
	let rearmed = 0;
	const timer = {set: delay => { assert.equal(delay, 60000); rearmed++; }};
	tick.call(timer);
	for (const p of [orphan, orphanStage, foreign, extra]) assert.ok(!fs.existsSync(p), p);
	for (const p of [fresh, pending, active, activeStage, unrecognized, path.join(foreignStage, 'core'),
		path.join(extraStage, 'core'), path.join(extraStage, 'user-data')]) assert.ok(fs.existsSync(p), p);
	receiving = pinned = false;
	tick.call(timer);
	for (const p of [pending, active, activeStage]) assert.ok(!fs.existsSync(p), p);
	assert.ok(fs.existsSync(fresh));
	assert.equal(rearmed, 2);
});
