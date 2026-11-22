import hashlib, json, os, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as tmp:
    t=Path(tmp)
    env={**os.environ, 'PATH':str(t)+':'+os.environ['PATH']}
    # 仅模拟 SDK 的构建基础设施, 执行真实的安装规则和翻译编译器.
    (t/'rules.mk').write_text('')
    (t/'package.mk').write_text('INSTALL_DIR=mkdir -p\n')
    (t/'main').mkdir(); (t/'lang').mkdir()
    harness=f'TOPDIR:={t}\nINCLUDE_DIR:={t}\ninclude {ROOT}/Makefile\nall:\n\t$(call Package/luci-app-adguardhome-tk/install,{t}/main)\n\t$(call Package/luci-i18n-adguardhome-tk-zh-cn/install,{t}/lang)\n'
    (t/'test.mk').write_text(harness)
    subprocess.run(['make','-s','-f',str(t/'test.mk')],cwd=ROOT,env=env,check=True,stdout=subprocess.DEVNULL,timeout=30)
    assert not list((t/'main').rglob('*.lmo'))
    assert (t/'main/etc/init.d/AdGuardHome').stat().st_mode & 0o111
    assert (t/'lang/usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo').stat().st_size > 0
    assert len([p for p in (t/'lang').rglob('*') if p.is_file()]) == 2
    print('PASS: separated payloads, translation compilation, executable permissions')
    # 模拟下载和安装命令, 验证不同版本的附件选择与下载失败行为.
    script=(ROOT/'scripts/install.sh').read_text().replace('/etc/init.d/rpcd reload', 'true').replace('rm -f /tmp/luci-indexcache /tmp/luci-indexcache.* /tmp/luci-modulecache/*', 'true')
    (t/'install.sh').write_text(script)
    (t/'uclient-fetch').write_text('''#!/bin/sh
if [ "$1" = -T ]; then shift 2; fi
case "$1" in --header=*) header=${1#--header=}; shift ;; esac
[ "$1" = -O ] || exit 2
output=$2
shift 2
case "$1" in
    */releases/latest)
        cat "$TEST_DIR/release.json"; exit ;;
esac
echo "$1" >> "$TEST_DIR/requests"
case "$1" in
    https://api.github.com/repos/w9315273/luci-app-adguardhome/releases/assets/*)
        [ "$header" = 'Accept: application/octet-stream' ] && [ "$FAIL_API" != 1 ] || exit 4
        case "${1##*/}" in
            101) name=luci-app-adguardhome-tk-2.6.1-r1.apk ;;
            202) name=luci-i18n-adguardhome-tk-zh-cn-2.6.1-r1.apk ;;
            *) exit 4 ;;
        esac ;;
    https://github.com/w9315273/luci-app-adguardhome/releases/download/*)
        [ "$FAIL_BROWSER" != 1 ] || exit 4
        name=${1##*/} ;;
    *) exit 4 ;;
esac
case "$name" in *luci-i18n*) [ "$FAIL_TRANSLATION" != 1 ] || exit 4 ;; esac
printf '%s' "$name" > "$output"
''')
    (t/'jsonfilter').write_text(r'''#!/usr/bin/env python3
import json, re, sys
m = re.fullmatch(r'@\.assets\[@\.name="([^"]+)"\]\.(id|digest)', sys.argv[-1])
if not m: sys.exit(1)
for asset in json.load(sys.stdin)['assets']:
    if asset['name'] == m[1] and m[2] in asset:
        print(asset[m[2]])
        sys.exit(0)
sys.exit(1)
''')
    (t/'apk').write_text('''#!/bin/sh
[ "$1" != info ] || exit 0
[ "$1" = add ] || exit 1
shift 2
for file in "$@"; do cat "$file"; echo; done > "$TEST_DIR/installed"
''')
    for name in ['uclient-fetch','jsonfilter','apk']: (t/name).chmod(0o755)
    def install(release, **failures):
        for name in ['installed', 'requests']:
            (t/name).unlink(missing_ok=True)
        (t/'release.json').write_text(json.dumps(release, indent=2))
        return subprocess.run(['sh',str(t/'install.sh'),'zh-cn'], env={**env, 'TEST_DIR':tmp, **failures},
                              capture_output=True, text=True, timeout=30)

    for split,fail in [(False,False),(True,False),(True,True)]:
        release={'tag_name':'v2.6.0-1','assets':[{'name':'luci-i18n-adguardhome-zh-cn-2.6.0-r1.apk'}] if split else []}
        result=install(release, FAIL_TRANSLATION=str(int(fail)))
        if fail:
            assert result.returncode != 0 and not (t/'installed').exists(), result.stdout
        else:
            assert result.returncode == 0, result.stderr
            installed=(t/'installed').read_text().splitlines()
            assert len(installed)==(2 if split else 1), installed
            assert all('/v2.6.0-1/' in url and url.endswith('2.6.0-r1.apk') for url in (t/'requests').read_text().splitlines())
    print('PASS: legacy release, split release, failed translation download aborts installation')

    names=['luci-app-adguardhome-tk-2.6.1-r1.apk','luci-i18n-adguardhome-tk-zh-cn-2.6.1-r1.apk']
    assets=[{'name':name, 'id':asset_id, 'digest':'sha256:'+hashlib.sha256(name.encode()).hexdigest()}
            for name,asset_id in zip(names,[101,202])]
    release={'tag_name':'v2.6.1-1', 'assets':assets}
    api_urls=[f"https://api.github.com/repos/w9315273/luci-app-adguardhome/releases/assets/{a['id']}" for a in assets]
    browser_urls=[f'https://github.com/w9315273/luci-app-adguardhome/releases/download/v2.6.1-1/{name}' for name in names]
    for fail_api in (False, True):
        result=install(release, FAIL_API=str(int(fail_api)))
        assert result.returncode == 0, result.stderr
        assert (t/'installed').read_text().splitlines() == names
        expected=[url for pair in zip(api_urls,browser_urls) for url in pair] if fail_api else api_urls
        assert (t/'requests').read_text().splitlines() == expected
    result=install(release, FAIL_API='1', FAIL_BROWSER='1')
    assert result.returncode != 0 and not (t/'installed').exists()
    assert (t/'requests').read_text().splitlines() == [api_urls[0],browser_urls[0]]
    assert names[0] in result.stderr
    assets[1]['digest']='sha256:'+'0'*64
    result=install(release)
    assert result.returncode != 0 and not (t/'installed').exists()
    assert 'SHA-256' in result.stderr and names[1] in result.stderr
    print('PASS: asset API, browser fallback, both sources unavailable, and checksum mismatch')
    collect=['bash',str(ROOT/'scripts/collect-apks.sh')]
    (t/'sdk/bin/packages').mkdir(parents=True)
    for package in ['luci-app-adguardhome-tk','luci-i18n-adguardhome-tk-zh-cn']:
        (t/f'sdk/bin/packages/{package}-2.6.0-r1.apk').touch()
    subprocess.run(collect,env={**env,'SDK_DIR':str(t/'sdk'),'GITHUB_WORKSPACE':tmp,'PKG_DIR_NAME':'luci-app-adguardhome-tk'},check=True,timeout=30)
    assert len(list((t/'dist').glob('*.apk')))==2
    (t/'sdk/bin/packages/luci-i18n-adguardhome-tk-zh-cn-2.6.0-r1.apk').unlink()
    result=subprocess.run(collect,env={**env,'SDK_DIR':str(t/'sdk'),'GITHUB_WORKSPACE':tmp,'PKG_DIR_NAME':'luci-app-adguardhome-tk'},capture_output=True,timeout=30)
    assert result.returncode != 0
    print('PASS: collects both APKs, rejects missing translation')
