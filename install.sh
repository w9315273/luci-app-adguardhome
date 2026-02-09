#!/bin/sh
set -e

REPO="w9315273/luci-app-adguardhome"

echo "Getting latest version..."
TAG=$(uclient-fetch -qO- "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
  | sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)

[ -n "$TAG" ] || { echo "ERROR: Failed to get latest version"; exit 1; }

VERSION=${TAG#v}
VERSION=${VERSION%-*}-r${VERSION##*-}

URL="https://github.com/${REPO}/releases/download/${TAG}/luci-app-adguardhome-${VERSION}.apk"

echo "Version: $VERSION"
echo "Downloading..."
uclient-fetch -qO /tmp/agh.apk "$URL"

echo "Installing..."
apk add --allow-untrusted /tmp/agh.apk

rm -f /tmp/agh.apk
echo "Done!"