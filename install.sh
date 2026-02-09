#!/bin/sh
set -e
REPO="w9315273/luci-app-adguardhome"
URL=$(uclient-fetch -qO- "https://api.github.com/repos/${REPO}/releases/latest" | grep "browser_download_url.*\.apk" | cut -d '"' -f 4)
uclient-fetch -O /tmp/agh.apk "$URL" && apk add --allow-untrusted /tmp/agh.apk && rm -f /tmp/agh.apk