#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
APK="${APK:-$(command -v apk || true)}"
if [[ ! -x "$APK" ]]; then
    echo 'APK v3 is required; add it to PATH or set APK to its executable path.' >&2
    exit 1
fi
APK="$(realpath "$APK")"
TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agh-apk-test.XXXXXX")"
export APK TEST_DIR
trap 'rm -rf -- "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/pkgs" "$TEST_DIR/bin"
cd "$TEST_DIR"
mkdir -p old/etc/config old/usr/lib/lua/luci/i18n new/etc/config lang/usr/lib/lua/luci/i18n
printf original > old/etc/config/AdGuardHome
printf translation > old/usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo
cp old/etc/config/AdGuardHome new/etc/config/
cp old/usr/lib/lua/luci/i18n/* lang/usr/lib/lua/luci/i18n/
"$APK" mkpkg -I name:luci-app-adguardhome -I version:99.0-r1 -I arch:noarch -F old -o pkgs/old.apk
"$APK" mkpkg -I name:luci-i18n-adguardhome-zh-cn -I version:99.0-r1 -I arch:noarch -I depends:luci-app-adguardhome -F lang -o pkgs/old-lang.apk
"$APK" mkpkg -I name:luci-app-adguardhome-tk -I version:2.6.0-r1 -I arch:noarch -I provides:luci-app-adguardhome=2.6.0-r1 -F new -o pkgs/luci-app-adguardhome-tk-2.6.0-r1.apk
"$APK" mkpkg -I name:luci-i18n-adguardhome-tk-zh-cn -I version:2.6.0-r1 -I arch:noarch -I depends:luci-app-adguardhome-tk -I provides:luci-i18n-adguardhome-zh-cn=2.6.0-r1 -F lang -o pkgs/luci-i18n-adguardhome-tk-zh-cn-2.6.0-r1.apk
# 使用真实安装脚本和 APK 依赖求解器, 隔离网络和路由器服务操作.
sed -e 's@/etc/init.d/rpcd reload@true@' -e 's@rm -f /tmp/luci-indexcache /tmp/luci-indexcache.\* /tmp/luci-modulecache/\*@true@' "$REPO_DIR/scripts/install.sh" > install.sh
cat > bin/apk <<'SH'
#!/bin/sh
case "$1" in
    add|del|upgrade) command=$1; shift; set -- "$command" --no-scripts "$@" ;;
esac
exec "$APK" --root "$TEST_ROOT" --no-network "$@"
SH
cat > bin/uclient-fetch <<'SH'
#!/bin/sh
if [ "$1" = -qO- ]; then
    printf '{\n"tag_name": "v2.6.0-1",\n"assets": [\n{"name": "luci-app-adguardhome-tk-2.6.0-r1.apk"},\n{"name": "luci-i18n-adguardhome-tk-zh-cn-2.6.0-r1.apk"}\n]}\n'
else
    case "$3" in *luci-i18n*) [ "${FAIL_DOWNLOAD:-0}" != 1 ] || exit 1 ;; esac
    cp "$TEST_DIR/pkgs/${3##*/}" "$2"
fi
SH
chmod +x bin/*
export PATH="$TEST_DIR/bin:$PATH"
for scenario in fresh bundled split; do
    export TEST_ROOT="$TEST_DIR/$scenario-root"
    if [ "$scenario" = fresh ]; then
        apk --allow-untrusted --initdb add
    else
        apk --allow-untrusted --initdb add "$TEST_DIR/pkgs/old.apk"
        if [ "$scenario" = split ]; then
            # 旧版拆分后的主包不再包含翻译文件, 避免构造重复文件所有权.
            rm old/usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo
            "$APK" mkpkg -I name:luci-app-adguardhome -I version:99.0-r2 -I arch:noarch -F old -o pkgs/old-split.apk
            apk --allow-untrusted add "$TEST_DIR/pkgs/old-split.apk" "$TEST_DIR/pkgs/old-lang.apk"
        fi
        printf customized > "$TEST_ROOT/etc/config/AdGuardHome"
        if FAIL_DOWNLOAD=1 sh install.sh zh-cn; then exit 1; fi
        apk info | grep -qx luci-app-adguardhome
        test "$(cat "$TEST_ROOT/etc/config/AdGuardHome")" = customized
    fi
    sh install.sh zh-cn
    test "$(apk info | sort)" = "$(printf '%s\n' luci-app-adguardhome-tk luci-i18n-adguardhome-tk-zh-cn | sort)"
    test "$(wc -l < "$TEST_ROOT/etc/apk/world")" = 2
    if grep -Eq '^luci-app-adguardhome([<=>~@]|$)|^luci-i18n-adguardhome-zh-cn([<=>~@]|$)' "$TEST_ROOT/etc/apk/world"; then
        echo "FAIL: legacy world constraints remain after $scenario migration" >&2
        exit 1
    fi
    test -f "$TEST_ROOT/usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo"
    if [ "$scenario" != fresh ]; then test "$(cat "$TEST_ROOT/etc/config/AdGuardHome")" = customized; fi
    sh install.sh zh-cn
    "$APK" mkndx --allow-untrusted --output "$TEST_DIR/pkgs/index.adb" "$TEST_DIR/pkgs/old.apk" "$TEST_DIR/pkgs/luci-app-adguardhome-tk-2.6.0-r1.apk" "$TEST_DIR/pkgs/luci-i18n-adguardhome-tk-zh-cn-2.6.0-r1.apk"
    apk upgrade --available --allow-untrusted --repository "$TEST_DIR/pkgs/index.adb"
    test "$(apk info | sort)" = "$(printf '%s\n' luci-app-adguardhome-tk luci-i18n-adguardhome-tk-zh-cn | sort)"
    echo "PASS: $scenario migration, reinstall and upgrade with higher-version official package"
done

for scenario in fresh old-split new-chinese; do
    export TEST_ROOT="$TEST_DIR/en-$scenario-root"
    case "$scenario" in
        fresh) apk --allow-untrusted --initdb add ;;
        old-split) apk --allow-untrusted --initdb add "$TEST_DIR/pkgs/old-split.apk" "$TEST_DIR/pkgs/old-lang.apk" ;;
        new-chinese) apk --allow-untrusted --initdb add "$TEST_DIR/pkgs/luci-app-adguardhome-tk-2.6.0-r1.apk" "$TEST_DIR/pkgs/luci-i18n-adguardhome-tk-zh-cn-2.6.0-r1.apk" ;;
    esac
    FAIL_DOWNLOAD=1 sh install.sh en
    test "$(apk info)" = luci-app-adguardhome-tk
    test ! -f "$TEST_ROOT/usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo"
    test "$(wc -l < "$TEST_ROOT/etc/apk/world")" = 1
    sh install.sh en
    echo "PASS: English $scenario installs only main package and removes old translations"
done
