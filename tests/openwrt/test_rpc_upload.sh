#!/bin/sh
set -eu

# 在装有插件的 OpenWrt 上检查实际 rpcd 模块及其 fs 依赖.
rpc=luci.adguardhome
root=/var/run/AdGuardHome-uploads
tokens=

cancel_upload() {
	ubus call "$rpc" cancelCoreUpload "{\"token\":\"$1\"}"
}

cleanup() {
	for token in $tokens; do
		cancel_upload "$token" >/dev/null || :
	done
}
trap cleanup EXIT

info=$(ubus call "$rpc" getCoreInfo)
case "$(jsonfilter -s "$info" -e '@.core_exists')" in
	true|false) ;;
	*) echo "Missing core status" >&2; exit 1 ;;
esac

for attempt in 1 2; do
	upload=$(ubus call "$rpc" prepareCoreUpload)
	token=$(jsonfilter -s "$upload" -e '@.token')
	case "$token" in
		*[!A-Za-z0-9]*|'') echo "Invalid upload token" >&2; exit 1 ;;
	esac
	[ "${#token}" -eq 6 ]
	case " $tokens " in
		*" $token "*) echo "Reused upload token" >&2; exit 1 ;;
	esac
	tokens="${tokens:+$tokens }$token"
	dir="$root/$token"
	[ "$(jsonfilter -s "$upload" -e '@.path')" = "$dir/payload" ]
	[ "$(ls -ldn "$dir" | awk '{print $1, $3}')" = 'drwx------ 0' ]
	[ -s "$dir/.session" ]
done

for token in $tokens; do
	result=$(cancel_upload "$token")
	[ "$(jsonfilter -s "$result" -e '@.cancelled')" = true ]
	[ ! -e "$root/$token" ]
done
tokens=
echo "RPC status and upload sessions passed"
