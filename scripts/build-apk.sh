#!/usr/bin/env bash
set -euo pipefail
cd "$SDK_DIR"

mkdir -p package/${PKG_DIR_NAME}
rsync -a --delete "$GITHUB_WORKSPACE/" "package/${PKG_DIR_NAME}/" \
  --exclude '.git*' --exclude '.local' --exclude '_sdk' --exclude 'dist'

./scripts/feeds update -a
./scripts/feeds install luci-base tar

touch .config
sed -i -E '/^(# )?CONFIG_(ALL|ALL_KMODS|ALL_NONSHARED|LUCI_LANG_zh_Hans|PACKAGE_TAR_XZ|PACKAGE_luci-app-adguardhome-tk|PACKAGE_luci-i18n-adguardhome-tk-zh-cn)(=| is not set)/d' .config
printf '%s\n' \
  'CONFIG_ALL=n' \
  'CONFIG_ALL_KMODS=n' \
  'CONFIG_ALL_NONSHARED=n' \
  'CONFIG_LUCI_LANG_zh_Hans=y' \
  '# CONFIG_PACKAGE_TAR_XZ is not set' \
  'CONFIG_PACKAGE_luci-app-adguardhome-tk=y' >> .config
make defconfig
if ! grep -Eq '^CONFIG_PACKAGE_luci-app-adguardhome-tk=(y|m)$' .config; then
  echo '::error::luci-app-adguardhome-tk was not enabled after make defconfig'
  grep -n 'luci-app-adguardhome-tk' .config || true
  sed -n '/^[[:space:]]*config PACKAGE_luci-app-adguardhome-tk$/,/^[[:space:]]*help/p' tmp/.config-package.in
  exit 1
fi

grep -Eq '^CONFIG_PACKAGE_luci-i18n-adguardhome-tk-zh-cn=(y|m)$' .config || {
  echo '::error::Simplified Chinese translation package was not enabled'
  exit 1
}

make package/compile -j"$(nproc)" V=sc
