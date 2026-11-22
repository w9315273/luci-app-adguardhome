"""用真实 DOM 验证操作列对齐, 备份期间的按钮和反馈, 以及恢复和删除的目标记录."""
import base64
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIEW = (ROOT / 'root/www/luci-static/resources/view/adguardhome/backup.js').read_text()

with sync_playwright() as runtime:
    browser = runtime.chromium.launch()
    page = browser.new_page()
    page.add_style_tag(content='.cbi-button { background-color: royalblue; color: white; }')
    page.add_style_tag(path=ROOT / 'root/www/luci-static/resources/view/adguardhome/compact.css')
    page.evaluate("""source => {
        function E(tag, attrs, children) {
            const el = document.createElement(tag);
            for (const [key, value] of Object.entries(attrs || {})) {
                if (key === 'click') el.addEventListener('click', value);
                else el.setAttribute(key, value);
            }
            if (children != null) el.append(...[children].flat());
            return el;
        }
        window.historyData = { state: 'idle', entries: [], core_exists: false, config_exists: true };
        window.actions = [];
        window.editable = true;
        const rpc = { declare: spec => spec.method === 'getBackupHistory' ? async () => structuredClone(historyData) :
            async (action, id) => {
                actions.push([action, id]);
                if (window.startGate) await startGate;
                if (window.rejectBusy) return {started: false, reason: 'busy'};
                historyData.state = 'running';
                return {started: true};
            } };
        const ui = {
            showModal(title, body) { document.body.append(E('div', {role: 'dialog'}, body)); },
            hideModal() { document.querySelector('[role=dialog]').remove(); }
        };
        const view = new Function('view', 'poll', 'rpc', 'ui', 'status', 'L', 'E', '_', source)(
            {extend: x => x}, {add: fn => window.refreshHistory = fn}, rpc, ui,
            {render: () => ({node: E('header'), refresh() {}})},
            {resource: () => 'data:text/css,', hasViewPermission: () => editable}, E, x => x);
        window.mount = async () => document.body.replaceChildren(view.render(await view.load()));
        return mount();
    }""", VIEW)
    create_core = page.locator('button[data-action="backup-core"]')
    create_config = page.locator('button[data-action="backup-config"]')
    rows = page.locator('.agh-backup-entry')
    dialog = page.get_by_role('dialog')
    feedback = page.locator('.agh-backup-status')

    def restore_button(row, component):
        return rows.nth(row).locator(f'button[data-action="restore-{component}"]')

    def delete_button(row):
        return rows.nth(row).locator('button[data-action="delete"]')

    expect(create_core).to_be_disabled()
    expect(create_core).to_be_hidden()
    expect(create_config).to_be_enabled()
    expect(page.get_by_text('No backups yet.')).to_be_visible()
    expect(page.get_by_text('3 automatic backups, 5 manual core backups, and 5 manual YAML backups', exact=False)).to_be_visible()
    expect(feedback).to_have_text('No core is installed. YAML backups and restores will skip validation.')
    create_config.click()
    assert page.evaluate('actions') == [['backup-config', '']]
    expect(create_core).to_be_hidden()
    expect(create_config).to_be_visible()
    expect(create_config).to_be_disabled()
    expect(feedback).to_have_text('')

    skipped = 'YAML validation skipped: no core is installed.'
    invalid = 'YAML configuration validation failed.'
    for state, label, detail in [('backed_up', '', skipped), ('restored', '', skipped),
                                 ('backup_failed', 'Backup failed', invalid), ('restore_failed', 'Restore failed', invalid)]:
        page.evaluate('''result => { Object.assign(historyData, result); return refreshHistory(); }''',
                      {'state': state, 'detail': detail, 'core_exists': detail == invalid})
        expect(feedback).to_have_text(f'{label}: {detail}' if label else detail)

    entries = [
        dict(id='1795392000-0002', created=1795392000, source='manual', version=None, has_core=False, has_config=True),
        dict(id='1795392000-0001', created=1795392000, source='manual', version='v1.0.0', has_core=True, has_config=False),
        dict(id='1795392000-0000', created=1795392000, source='update', version='v1.0.0', has_core=True, has_config=True),
        dict(id='legacy', created=1795305600, source='legacy', version='v0.107.80', has_core=True, has_config=False),
    ]
    page.evaluate('''entries => {
        Object.assign(historyData, {entries, state:'idle', detail:'', core_exists:true, config_exists:false});
        return refreshHistory();
    }''', entries)
    expect(create_core).to_be_enabled()
    expect(create_config).to_be_disabled()
    expect(create_config).to_be_hidden()
    expect(feedback).to_have_text('The YAML configuration file is missing.')
    expect(rows).to_have_count(4)
    for i, entry in enumerate(entries):
        expect(delete_button(i)).to_be_visible()
        expect(delete_button(i)).to_have_class('btn cbi-button cbi-button-remove')
        for part in ('core', 'config'):
            button = restore_button(i, part)
            if entry['has_' + part]:
                expect(button).to_be_visible()
                expect(button).to_be_enabled()
            else:
                expect(button).to_have_count(0)
        expect(restore_button(i, 'both')).to_have_count(int(entry['has_core'] and entry['has_config']))
    assert 'null' not in rows.first.inner_text()

    page.evaluate("() => { historyData.config_exists = true; return refreshHistory(); }")
    expect(create_config).to_be_visible()
    wide_positions = []
    for width in (1120, 1440, 700, 390, 320):
        page.set_viewport_size({'width': width, 'height': 850})
        if width > 760:
            first_action = create_core.bounding_box()['x']
            wide_positions.append(first_action)
            last_label = rows.locator('time, .agh-backup-source, .agh-backup-file').evaluate_all(
                'labels => Math.max(...labels.map(label => label.getBoundingClientRect().right))')
            assert 0 <= first_action - last_label <= 40, (width, last_label, first_action)
        for part, create in [('core', create_core), ('config', create_config)]:
            header = create.bounding_box()
            for i, entry in enumerate(entries):
                if not entry['has_' + part]:
                    continue
                box = restore_button(i, part).bounding_box()
                assert abs(box['x'] - header['x']) <= 1, (width, i, part, header, box)
                assert abs(box['width'] - header['width']) <= 1, (width, i, part, header, box)
        delete_x = delete_button(0).bounding_box()['x']
        config_box = create_config.bounding_box()
        both = restore_button(2, 'both').bounding_box()
        core = restore_button(2, 'core').bounding_box()
        config = restore_button(2, 'config').bounding_box()
        if width <= 480:
            assert both['y'] >= core['y'] + core['height']
            assert abs(both['x'] - core['x']) <= 1
            assert abs(both['x'] + both['width'] - config['x'] - config['width']) <= 1
        else:
            assert both['x'] >= config['x'] + config['width']
        assert delete_x >= both['x'] + both['width']
        assert delete_x >= config_box['x'] + config_box['width']
        for i in range(len(entries)):
            box = delete_button(i).bounding_box()
            assert abs(box['x'] - delete_x) <= 1 and box['x'] + box['width'] <= width, (width, i, box)
    assert abs(wide_positions[0] - wide_positions[1]) <= 1, wide_positions

    restore_button(3, 'core').click()
    expect(dialog.get_by_role('button', name='Restore core')).to_be_visible()
    dialog.get_by_role('button', name='Cancel').click()
    assert len(page.evaluate('actions')) == 1

    busy = 'Another core task is running. This operation did not start. Try again when it finishes.'
    restore_button(2, 'both').click()
    expect(dialog).to_contain_text('Restore the core and YAML configuration together from this backup?')
    expect(dialog).to_contain_text(entries[2]['version'])
    page.evaluate("() => { historyData.state = 'running'; return refreshHistory(); }")
    dialog.get_by_role('button', name='Restore both').click()
    assert len(page.evaluate('actions')) == 1
    expect(feedback).to_have_text(busy)
    page.evaluate("() => { historyData.state = 'restored'; return refreshHistory(); }")
    expect(feedback).to_have_text(busy)
    restore_button(2, 'both').click()
    page.evaluate("() => { window.rejectBusy = true; }")
    dialog.get_by_role('button', name='Restore both').click()
    assert page.evaluate('actions')[-1] == ['restore-both', entries[2]['id']]
    expect(feedback).to_have_text(busy)
    page.evaluate("() => { window.rejectBusy = false; }")
    restore_button(2, 'both').click()
    dialog.get_by_role('button', name='Restore both').click()
    expect(restore_button(2, 'both')).to_be_disabled()
    assert page.evaluate('actions')[-1] == ['restore-both', entries[2]['id']]
    page.evaluate("() => { historyData.state = 'restored'; return refreshHistory(); }")
    expect(feedback).to_have_text('')

    delete_button(3).click()
    expect(dialog).to_contain_text(rows.nth(3).locator('time').inner_text())
    expect(dialog).to_contain_text('Legacy backup / Core v0.107.80')
    expect(dialog).not_to_contain_text('YAML')
    dialog.get_by_role('button', name='Cancel').click()
    assert page.evaluate('actions')[-1] == ['restore-both', entries[2]['id']]

    delete_button(2).click()
    expect(dialog).to_contain_text('Before core update / Core v1.0.0 / YAML')
    expect(dialog).to_contain_text('Permanently delete this backup from the router?')
    page.evaluate('''() => { historyData.entries = historyData.entries.toReversed(); return refreshHistory(); }''')
    dialog.get_by_role('button', name='Delete backup').click()
    assert page.evaluate('actions')[-1] == ['delete', entries[2]['id']]
    expect(feedback).to_have_text('')
    expect(delete_button(0)).to_be_disabled()
    page.evaluate('''() => {
        Object.assign(historyData, {state:'delete_failed', detail:'Failed to delete the selected backup.'});
        return refreshHistory();
    }''')
    expect(feedback).to_have_text('Delete failed: Failed to delete the selected backup.')
    expect(rows).to_have_count(4)

    delete_button(0).click()
    dialog.get_by_role('button', name='Delete backup').click()
    assert page.evaluate('actions')[-1] == ['delete', 'legacy']
    page.evaluate('''entries => {
        Object.assign(historyData, {entries, state:'deleted', detail:''});
        return refreshHistory();
    }''', entries[:3])
    expect(feedback).to_have_text('')
    expect(rows).to_have_count(3)

    restore_button(2, 'config').click()
    page.evaluate('''() => { historyData.entries = historyData.entries.slice(0, 2); return refreshHistory(); }''')
    dialog.get_by_role('button', name='Restore configuration').click()
    assert page.evaluate('actions')[-1] == ['restore-config', entries[2]['id']]
    expect(restore_button(1, 'core')).to_be_disabled()
    expect(create_core).to_be_disabled()
    expect(create_config).to_be_disabled()

    def finish_action(state):
        page.evaluate("state => { historyData.state = state; return refreshHistory(); }", state)
        expect(feedback).to_have_text('')

    finish_action('restored')
    restore_button(1, 'core').click()
    dialog.get_by_role('button', name='Restore core').click()
    assert page.evaluate('actions')[-1] == ['restore-core', entries[1]['id']]
    finish_action('restored')

    def background_chroma(button):
        # 读取浏览器渲染后的背景像素, 兼容主题颜色和 CSS 滤镜.
        png = base64.b64encode(button.screenshot()).decode('ascii')
        return page.evaluate("""async png => {
            const image = new Image();
            image.src = 'data:image/png;base64,' + png;
            await image.decode();
            const canvas = document.createElement('canvas');
            canvas.width = image.width;
            canvas.height = image.height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(image, 0, 0);
            const [r, g, b] = ctx.getImageData(4, Math.floor(image.height / 2), 1, 1).data;
            return Math.max(r, g, b) - Math.min(r, g, b);
        }""", png)

    controls = page.locator('.agh-backup-layout button').all()
    boxes = [button.bounding_box() for button in controls]
    assert background_chroma(create_core) > 40
    page.evaluate("() => { window.startGate = new Promise(resolve => { window.allowStart = resolve; }); }")
    create_core.click()
    assert page.evaluate('actions')[-1] == ['backup-core', '']
    expected_actions = page.evaluate('actions')

    def check_busy_controls():
        for button, before in zip(controls, boxes):
            expect(button).to_be_visible()
            expect(button).to_be_disabled()
            assert button.bounding_box() == before
            button.evaluate('el => el.click()')
        expect(dialog).to_have_count(0)
        assert page.evaluate('actions') == expected_actions
        assert background_chroma(create_core) < 15
        expect(feedback).to_have_text('')

    check_busy_controls()
    page.evaluate('() => { window.allowStart(); }')
    page.wait_for_function("historyData.state === 'running'")
    page.evaluate('() => refreshHistory()')
    check_busy_controls()
    finish_action('backed_up')
    for button in controls:
        expect(button).to_be_enabled()
    assert background_chroma(create_core) > 40
    for state, label in [('rollback_failed', 'Rollback incomplete. The previous files are kept for the next attempt.'),
                         ('rollback_start_failed', 'The previous files were restored, but the original service failed to start.')]:
        page.evaluate("state => { historyData.state = state; return refreshHistory(); }", state)
        expect(feedback).to_have_text(label)
    warning = 'Could not prune the oldest manual backup.'
    page.evaluate("text => { Object.assign(historyData, {state:'backed_up', warnings:[text]}); return refreshHistory(); }", warning)
    expect(feedback).to_have_text(warning)
    damaged = dict(id='1795392001-0001', created=1795392001, source='update', version=None, has_core=False,
                   has_config=True, damaged_core=True)
    page.evaluate("entry => { historyData.entries.push(entry); historyData.warnings = []; return refreshHistory(); }", damaged)
    expect(rows.nth(2)).to_contain_text('Damaged core')
    expect(restore_button(2, 'core')).to_have_count(0)
    expect(restore_button(2, 'both')).to_have_count(0)
    expect(restore_button(2, 'config')).to_be_enabled()
    expect(delete_button(2)).to_be_enabled()
    page.evaluate("() => { editable = false; historyData.state = 'idle'; return mount(); }")
    for button in (create_core, create_config, restore_button(0, 'config'), restore_button(1, 'core'),
                   delete_button(0), delete_button(1)):
        expect(button).to_be_disabled()
        expect(button).to_be_hidden()
    browser.close()
