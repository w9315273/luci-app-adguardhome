#!/bin/sh

PATH="/usr/sbin:/usr/bin:/sbin:/bin"
state_file=/var/run/AdGuardHome-update.state
core_api_url="https://api.github.com/repos/AdguardTeam/AdGuardHome/releases/latest"

get_arch() {
	local arch machine
	machine="$(uname -m)"
	if command -v apk >/dev/null 2>&1; then
		arch="$(apk --print-arch 2>/dev/null)"
	elif command -v opkg >/dev/null 2>&1; then
		arch="$(opkg print-architecture 2>/dev/null | awk '$1 == "arch" && $2 != "all" && $2 != "noarch" && $3 >= priority {arch=$2; priority=$3} END {print arch}')"
	fi
	arch=${arch:-$machine}
	printf '设备架构: %s\n' "$arch" >&2
	case "$arch" in
		x86_64|x86_64_*|amd64) echo amd64 ;;
		i[3-6]86*|x86|pentium4|pentium-mmx|geode) echo 386 ;;
		aarch64_be*|armeb*|armv*b|armv4*|arm_fa526*) return 1 ;;
		aarch64|aarch64_*|arm64) echo arm64 ;;
		armv5*|arm_xscale*|arm_fa626*) echo armv5 ;;
		armv6*|arm_arm11*|arm_mpcore*) echo armv6 ;;
		armv7*|armv8l|arm_cortex-a*) echo armv7 ;;
		arm|arm_*)
			case "$machine" in
				armv5*l) echo armv5 ;;
				armv6*l) echo armv6 ;;
				armv7*l|armv8l|aarch64) echo armv7 ;;
				*) return 1 ;;
			esac ;;
		mips64el*|mips64le*) echo mips64le_softfloat ;;
		mips64|mips64_*) echo mips64_softfloat ;;
		mipsel*|mipsle*) echo mipsle_softfloat ;;
		mips|mips_*) echo mips_softfloat ;;
		powerpc64le*|ppc64le*) echo ppc64le ;;
		riscv64*) echo riscv64 ;;
		*) return 1 ;;
	esac
}

core_version() {
	"$1" --version 2>/dev/null | sed -n 's/.*version \(v[^,[:space:]]*\).*/\1/p' | head -n 1
}

owns_web_listener() {
	local pid="$1" port="$2"
	[ -n "$pid" ] && [ "$binpath" -ef "/proc/$pid/exe" ] || return 1
	set -- /proc/net/tcp
	[ ! -r /proc/net/tcp6 ] || set -- "$@" /proc/net/tcp6
	ls -l "/proc/$pid/fd" 2>/dev/null | awk -v port="$port" '
		FILENAME != "-" && $4 == "0A" && $2 ~ (":" port "$") { sockets["socket:[" $10 "]"] = 1 }
		FILENAME == "-" && $NF in sockets { found = 1 }
		END { exit !found }
	' "$@" -
}

wait_for_core() {
	local port pid previous="" stable=0 tries=0
	port="$(uci get AdGuardHome.AdGuardHome.httpport 2>/dev/null)"
	port="$(awk -v port="${port:-3000}" 'BEGIN {printf "%04X", port}')"
	while [ "$tries" -lt 20 ]; do
		pid="$(ubus call service list '{"name":"AdGuardHome"}' 2>/dev/null | jsonfilter -e '@.AdGuardHome.instances.instance1.pid')"
		if owns_web_listener "$pid" "$port"; then
			[ "$pid" = "$previous" ] || stable=0
			stable=$((stable + 1))
			[ "$stable" -lt 3 ] || return 0
		else
			stable=0
		fi
		previous="$pid"
		tries=$((tries + 1))
		sleep 1
	done
	return 1
}

fetch_archive() {
	local url="$1" rc
	shift
	printf '下载链接: %s\n' "$url"
	uclient-fetch -T 20 "$@" -O "$work/core.tar.gz" "$url" 2>"$work/fetch.log" && return 0
	rc=$?
	printf '下载失败 (uclient-fetch 退出码 %s).\n' "$rc"
	# 仅显示最后一条诊断, 去掉重定向地址中临时签名的查询参数.
	tail -n 1 "$work/fetch.log" | cut -d '?' -f 1
	return "$rc"
}

update_core() {
	local binpath bindir current version arch name asset id url digest actual
	binpath="$(uci get AdGuardHome.AdGuardHome.binpath 2>/dev/null)"
	binpath=${binpath:-/usr/bin/AdGuardHome/AdGuardHome}
	printf '%s\n' '开始检查更新, 请耐心等待 ...'
	work="$(mktemp -d /tmp/AdGuardHome-update.XXXXXX)" || return 1
	if ! uclient-fetch -T 20 -q -O "$work/release.json" "$core_api_url" ||
	   ! version="$(jsonfilter -i "$work/release.json" -e '@.tag_name')" || [ -z "$version" ]; then
		printf '%s\n' '检查更新失败, 请检查网络或稍后重试!'
		return 1
	fi
	current="$(core_version "$binpath")"
	printf '\n执行文件路径: %s\n当前 AdGuardHome 版本: %s\n云端 AdGuardHome 版本: %s\n' "$binpath" "${current:-未知}" "$version"
	if [ "$current" = "$version" ] && [ "$1" != force ]; then
		printf '\n已是最新版本, 无需更新!\n'
		outcome=current
		return 0
	fi

	arch="$(get_arch)" || { printf '%s\n' '官方核心不支持当前设备架构.'; return 1; }
	name="AdGuardHome_linux_${arch}.tar.gz"
	asset="@.assets[@.name=\"$name\"]"
	url="$(jsonfilter -i "$work/release.json" -e "$asset.browser_download_url")"
	if [ -z "$url" ]; then
		printf '此版本未提供 %s.\n' "$name"
		return 1
	fi
	id="$(jsonfilter -i "$work/release.json" -e "$asset.id")"
	case "$id" in *[!0-9]*) id='' ;; esac
	printf '\n正在下载 %s ...\n' "$name"
	if [ -z "$id" ] || ! fetch_archive "${core_api_url%/latest}/assets/$id" --header='Accept: application/octet-stream'; then
		[ -z "$id" ] || printf '%s\n' '附件 API 下载失败, 正在尝试发布页直链.'
		fetch_archive "$url" || return 1
	fi
	digest="$(jsonfilter -i "$work/release.json" -e "$asset.digest")"
	if [ -n "$digest" ] && [ "$digest" != null ]; then
		actual="$(sha256sum "$work/core.tar.gz")" || return 1
		[ "$digest" = "sha256:${actual%% *}" ] || { printf '%s\n' '核心下载文件校验失败.'; return 1; }
	fi

	if [ -L "$binpath" ]; then
		binpath="$(readlink -f "$binpath")" || return 1
	fi
	[ ! -d "$binpath" ] || { printf '%s\n' '执行文件路径指向了目录.'; return 1; }
	bindir="$(dirname "$binpath")"
	mkdir -p "$bindir" || return 1
	staged="$(mktemp "$bindir/.AdGuardHome.XXXXXX")" || return 1
	if ! tar -xzOf "$work/core.tar.gz" ./AdGuardHome/AdGuardHome >"$staged" 2>/dev/null &&
	   ! tar -xzOf "$work/core.tar.gz" AdGuardHome/AdGuardHome >"$staged"; then
		printf '%s\n' '核心解压失败.'
		return 1
	fi
	chmod 755 "$staged" || return 1
	if [ "$(core_version "$staged")" != "$version" ]; then
		printf '%s\n' '新核心无法运行或版本与发行版本不符.'
		return 1
	fi
	mv -f "$staged" "$binpath" || return 1
	staged=''
	case "$(uci get AdGuardHome.AdGuardHome.enabled 2>/dev/null)" in
	1|on|true|yes|enabled)
		printf '\n正在重启 AdGuardHome 服务...\n'
		if ! /etc/init.d/AdGuardHome restart 9>&- || ! wait_for_core; then
			outcome=start_failed
			printf '%s\n' '新核心已安装, 服务未能正常启动, 请检查运行日志.'
			return 1
		fi
		;;
	esac
	printf '\nAdGuardHome 核心更新成功!\n'
	outcome=finished
}

cleanup() {
	local rc=$?
	trap - EXIT
	[ -z "$staged" ] || rm -f "$staged"
	[ -z "$work" ] || rm -rf "$work"
	printf '%s\n' "$outcome" >"$state_file"
	exit "$rc"
}

run_update() {
	outcome=failure work='' staged=''
	trap cleanup EXIT
	trap 'exit 1' TERM INT HUP
	update_core "$1"
}

exec 9>/var/lock/AdGuardHome-update.lock || exit 1
if ! flock -w 1 9; then
	printf '%s\n' '已有更新任务正在运行, 请等待其结束.'
	exit 2
fi
exec >/tmp/AdGuardHome_update.log 2>&1
printf 'running\n' >"$state_file" || exit 1
if [ "$1" = --background ]; then
	run_update "$2" </dev/null &
else
	run_update "$1"
fi
