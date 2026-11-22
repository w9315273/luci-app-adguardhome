#!/bin/sh
set -e

REPO="w9315273/luci-app-adguardhome"
LANGUAGE=${1:-en}
case "$LANGUAGE" in
    en|zh-cn) ;;
    *) echo "Usage: sh install.sh [en|zh-cn]"; exit 1 ;;
esac
[ "$#" -le 1 ] || { echo "Usage: sh install.sh [en|zh-cn]"; exit 1; }

echo "Getting latest version..."
RELEASE=$(uclient-fetch -T 20 -O - "https://api.github.com/repos/${REPO}/releases/latest") || {
    echo "ERROR: Failed to download release information" >&2
    exit 1
}
TAG=$(printf '%s\n' "$RELEASE" | sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)

[ -n "$TAG" ] || { echo "ERROR: Failed to get latest version"; exit 1; }

case "$TAG" in
  *-*) ;;
  *) echo "ERROR: Unexpected tag format: $TAG"; exit 1 ;;
esac

VERSION=${TAG#v}
VERSION=${VERSION%-*}-r${VERSION##*-}

PACKAGE=luci-app-adguardhome
I18N_PACKAGE=luci-i18n-adguardhome-zh-cn
if printf '%s\n' "$RELEASE" | grep -Eq '"name"[[:space:]]*:[[:space:]]*"luci-app-adguardhome-tk-[^"]*\.apk"'; then
    PACKAGE=luci-app-adguardhome-tk
    I18N_PACKAGE=luci-i18n-adguardhome-tk-zh-cn
fi
echo "Version: $VERSION"
work=$(mktemp -d /tmp/agh-install.XXXXXX)
trap 'rm -rf "$work"' EXIT

download_package() {
    local name="$1" dest="$2" asset id='' digest='' sum
    echo "Downloading $name..."
    if command -v jsonfilter >/dev/null 2>&1; then
        asset="@.assets[@.name=\"$name\"]"
        id=$(printf '%s\n' "$RELEASE" | jsonfilter -e "$asset.id") || id=''
        digest=$(printf '%s\n' "$RELEASE" | jsonfilter -e "$asset.digest") || digest=''
    fi

    case "$id" in
        ''|*[!0-9]*) id='' ;;
    esac
    if [ -z "$id" ] || ! uclient-fetch -T 20 --header='Accept: application/octet-stream' \
            -O "$dest" "https://api.github.com/repos/${REPO}/releases/assets/$id"; then
        echo "Trying the release download URL for $name..."
        uclient-fetch -T 20 -O "$dest" "https://github.com/${REPO}/releases/download/${TAG}/$name" || {
            echo "ERROR: Failed to download $name" >&2
            return 1
        }
    fi
    if [ -n "$digest" ] && [ "$digest" != null ]; then
        sum=$(sha256sum "$dest") || return 1
        [ "$digest" = "sha256:${sum%% *}" ] || {
            echo "ERROR: SHA-256 verification failed for $name" >&2
            return 1
        }
    fi
}

download_package "${PACKAGE}-${VERSION}.apk" "$work/main.apk"
set -- "$work/main.apk"

I18N="${I18N_PACKAGE}-${VERSION}.apk"
has_i18n=0
if [ "$LANGUAGE" = zh-cn ] && printf '%s\n' "$RELEASE" | grep -Eq "\"name\"[[:space:]]*:[[:space:]]*\"${I18N_PACKAGE}-[^\"]*\\.apk\""; then
    download_package "$I18N" "$work/zh-cn.apk"
    set -- "$@" "$work/zh-cn.apk"
    has_i18n=1
fi

if [ "$LANGUAGE" = zh-cn ] && [ "$PACKAGE" = luci-app-adguardhome-tk ] && [ "$has_i18n" != 1 ]; then
    echo "ERROR: The release is missing the Chinese package"
    exit 1
fi

legacy_packages=
if [ "$PACKAGE" = luci-app-adguardhome-tk ]; then
    installed=$(apk info)
    for old in luci-app-adguardhome luci-i18n-adguardhome-zh-cn; do
        if printf '%s\n' "$installed" | grep -qx "$old"; then
            if [ "$old" != luci-i18n-adguardhome-zh-cn ] || [ "$LANGUAGE" = zh-cn ]; then
                set -- "$@" "$old"
            fi
            legacy_packages="$legacy_packages $old"
        fi
    done
fi

echo "Installing..."
apk add --allow-untrusted "$@"
if [ -n "$legacy_packages" ]; then
    apk del $legacy_packages
fi

if [ "$LANGUAGE" = en ]; then
    installed=$(apk info)
    for translation in luci-i18n-adguardhome-zh-cn luci-i18n-adguardhome-tk-zh-cn; do
        if printf '%s\n' "$installed" | grep -qx "$translation"; then
            apk del "$translation"
        fi
    done
fi

echo "Refreshing LuCI..."
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.* /tmp/luci-modulecache/* 2>/dev/null
/etc/init.d/rpcd reload >/dev/null 2>&1

echo "Done."
