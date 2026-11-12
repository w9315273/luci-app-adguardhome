"""从页面提取复选框逻辑, 用真实 DOM 验证布尔属性和保存后的状态."""
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'root/www/luci-static/resources/view/adguardhome/log.js').read_text()
block = source[source.index("\t\t\tvar verboseToggle ="):source.index("\t\t\tvar message =")]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    result = page.evaluate('''async block => {
        function E(tag, attrs, children) {
            const node = document.createElement(tag);
            for (const key in attrs) if (attrs[key] != null) node.setAttribute(key, attrs[key]);
            return node;
        }
        const create = new Function('E', 'm', '_', 'callSetVerboseLog', 'var toggleStyle="";'+block+';return verboseToggle;');
        let saved = '0';
        let fail = false;
        const rpc = async enabled => { if (fail) throw Error('save failed'); saved = enabled ? '1' : '0'; return {saved:true, applied:true}; };
        const render = readonly => create(E, {data:{get:()=>saved}, readonly}, x=>x, rpc);
        const check = (ok,msg) => {if (!ok) throw Error(msg);};
        const tick = () => new Promise(resolve => setTimeout(resolve,0));
        let input = render(false); document.body.append(input);
        check(!input.checked && !input.disabled, 'default off and editable');
        input.click(); await tick();
        check(saved === '1' && render(false).checked, 'enable survives reload');
        input.click(); await tick();
        check(saved === '0' && !render(false).checked, 'disable survives reload');
        fail = true; input.click(); await tick();
        check(!input.checked && !input.disabled && saved === '0', 'failure restores state');
        check(render(true).disabled, 'readonly disabled');
        saved = undefined; check(!render(false).checked, 'missing setting defaults off');
        return 'PASS: default, enable/disable + reload, save failure, readonly, missing setting';
    }''', block)
    print(result)
    browser.close()
