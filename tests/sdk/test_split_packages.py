import json, os, subprocess, tempfile
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
if [ "$1" = -qO- ]; then cat "$TEST_DIR/release.json"; exit; fi
case "$3" in *luci-i18n*) [ "$FAIL_TRANSLATION" != 1 ] || exit 1 ;; esac
printf '%s' "$3" > "$2"
''')
    (t/'apk').write_text('''#!/bin/sh
shift 2
for file in "$@"; do cat "$file"; echo; done > "$TEST_DIR/installed"
''')
    for name in ['uclient-fetch','apk']: (t/name).chmod(0o755)
    for split,fail in [(False,False),(True,False),(True,True)]:
        (t/'installed').unlink(missing_ok=True)
        (t/'release.json').write_text(json.dumps({'tag_name':'v2.6.0-1','assets':[{'name':'luci-i18n-adguardhome-zh-cn-2.6.0-r1.apk'}] if split else []},indent=2))
        result=subprocess.run(['sh',str(t/'install.sh'),'zh-cn'],env={**env,'TEST_DIR':tmp,'FAIL_TRANSLATION':str(int(fail))},capture_output=True,text=True,timeout=30)
        if fail:
            assert result.returncode != 0 and not (t/'installed').exists(), result.stdout
        else:
            assert result.returncode == 0, result.stderr
            installed=(t/'installed').read_text().splitlines()
            assert len(installed)==(2 if split else 1), installed
            assert all('v2.6.0-1/' in url and url.endswith('2.6.0-r1.apk') for url in installed)
    print('PASS: legacy release, split release, failed translation download aborts installation')
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
