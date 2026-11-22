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
	printf 'Device architecture: %s\n' "$arch" >&2
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
	local output
	output="$("$1" --version 2>/dev/null)" || return 1
	printf '%s\n' "$output" | sed -n 's/.*version \(v[^,[:space:]]*\).*/\1/p' | head -n 1
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
	printf 'Download URL: %s\n' "$url"
	uclient-fetch -T 20 "$@" -O "$work/core.tar.gz" "$url" 2>"$work/fetch.log" && return 0
	rc=$?
	printf 'Download failed (uclient-fetch exit code): %s\n' "$rc"
	# 仅显示最后一条诊断, 去掉重定向地址中临时签名的查询参数.
	tail -n 1 "$work/fetch.log" | cut -d '?' -f 1
	return "$rc"
}

prepare_stage() {
	mkdir -p "$bindir" || return 1
	stage_dir="$(mktemp -d "$bindir/.AdGuardHome.XXXXXX")"
}

prepare_work() {
	[ -n "$work" ] || work="$(mktemp -d /tmp/AdGuardHome-update.XXXXXX)"
}

. /usr/share/AdGuardHome/core_backup.sh

restart_if_enabled() {
	case "$(uci get AdGuardHome.AdGuardHome.enabled 2>/dev/null)" in
	1|on|true|yes|enabled)
		printf '\nRestarting the AdGuard Home service...\n'
		(umask "$service_umask"; /etc/init.d/AdGuardHome restart 9>&-) && wait_for_core
		;;
	esac
}

update_core() {
	local current version arch name asset id url digest actual staged
	printf '%s\n' 'Checking for core updates...'
	prepare_work || return 1
	if ! uclient-fetch -T 20 -q -O "$work/release.json" "$core_api_url" ||
	   ! version="$(jsonfilter -i "$work/release.json" -e '@.tag_name')" || [ -z "$version" ]; then
		printf '%s\n' 'Update check failed. Check your network or try again later.'
		return 1
	fi
	current="$(core_version "$binpath")"
	printf '\nExecutable path: %s\nCurrent AdGuard Home version: %s\nLatest AdGuard Home version: %s\n' "$binpath" "${current:-unknown}" "$version"
	if [ "$current" = "$version" ] && [ "$1" != force ]; then
		printf '\nThe core is already up to date.\n'
		outcome=current
		return 0
	fi

	arch="$(get_arch)" || { printf '%s\n' 'The official core does not support this device architecture.'; return 1; }
	name="AdGuardHome_linux_${arch}.tar.gz"
	asset="@.assets[@.name=\"$name\"]"
	url="$(jsonfilter -i "$work/release.json" -e "$asset.browser_download_url")"
	if [ -z "$url" ]; then
		printf 'Archive unavailable for this release: %s\n' "$name"
		return 1
	fi
	id="$(jsonfilter -i "$work/release.json" -e "$asset.id")"
	case "$id" in *[!0-9]*) id='' ;; esac
	printf '\nDownloading: %s\n' "$name"
	if [ -z "$id" ] || ! fetch_archive "${core_api_url%/latest}/assets/$id" --header='Accept: application/octet-stream'; then
		[ -z "$id" ] || printf '%s\n' 'The asset API download failed. Trying the direct release URL.'
		fetch_archive "$url" || return 1
	fi
	digest="$(jsonfilter -i "$work/release.json" -e "$asset.digest")"
	if [ -n "$digest" ] && [ "$digest" != null ]; then
		actual="$(sha256sum "$work/core.tar.gz")" || return 1
		[ "$digest" = "sha256:${actual%% *}" ] || { printf '%s\n' 'Core archive checksum verification failed.'; return 1; }
	fi

	prepare_stage || return 1
	staged="$stage_dir/core"
	if ! tar -xzOf "$work/core.tar.gz" ./AdGuardHome/AdGuardHome >"$staged" 2>/dev/null &&
	   ! tar -xzOf "$work/core.tar.gz" AdGuardHome/AdGuardHome >"$staged"; then
		printf '%s\n' 'Failed to extract the core archive.'
		return 1
	fi
	chmod 755 "$staged" || return 1
	if [ "$(core_version "$staged")" != "$version" ]; then
		printf '%s\n' 'The new core could not run or reported an unexpected version.'
		return 1
	fi
	if [ "$(core_version "$binpath")" != "$current" ]; then
		printf '%s\n' 'The installed core changed. Try again.'
		return 1
	fi
	if [ -e "$binpath" ]; then
		save_snapshot update "$current" || { printf '%s\n' 'Failed to save the core and YAML backup.'; return 1; }
	fi
	mv -f "$staged" "$binpath" || return 1
	if ! restart_if_enabled; then
		outcome=start_failed
		printf '%s\n' 'The new core is installed, but the service failed to start. Check the runtime log.'
		return 1
	fi
	printf '\nAdGuard Home core updated successfully.\n'
	outcome=finished
}

cleanup() {
	local rc=$?
	trap - EXIT TERM INT HUP
	if [ "$restore_active" = 1 ]; then
		rollback_restore || printf '%s\n' 'Rollback incomplete. The previous files are kept for the next attempt.'
	fi
	[ -z "$snapshot_tmp" ] || rm -rf "$snapshot_tmp"
	[ -z "$config_stage" ] || rm -rf "$config_stage"
	[ -z "$stage_dir" ] || rm -rf "$stage_dir"
	[ -z "$work" ] || rm -rf "$work"
	printf '%s\n' "$outcome" >"$state_file"
	exit "$rc"
}

run_update() {
	outcome=failure work='' stage_dir='' snapshot_tmp='' config_stage='' restore_active=0
	trap cleanup EXIT
	trap 'exit 1' TERM INT HUP
	case "$1" in
		backup|backup-core|backup-config) outcome=backup_failed ;;
		restore|restore-core|restore-config) outcome=restore_failed ;;
		delete) outcome=delete_failed ;;
	esac
	binpath="$(uci get AdGuardHome.AdGuardHome.binpath 2>/dev/null)"
	binpath=${binpath:-/usr/bin/AdGuardHome/AdGuardHome}
	if [ -L "$binpath" ]; then
		binpath="$(readlink -f "$binpath")" || return 1
	fi
	[ ! -d "$binpath" ] || { printf '%s\n' 'The executable path points to a directory.'; return 1; }
	bindir="$(dirname "$binpath")"
	backup="$binpath.prev"
	history="$binpath.backups"
	pending="$binpath.restore-pending"
	service_umask="$(umask)"
	umask 077
	if [ "$1" = delete ]; then
		delete_snapshot "$2" || { printf '%s\n' 'Failed to delete the selected backup.'; return 1; }
		return 0
	fi
	if [ -e "$pending" ] || [ -L "$pending" ]; then
		rollback_restore || { printf '%s\n' 'Could not recover the interrupted restore.'; return 1; }
	fi
	case "$1" in
		backup|backup-core|backup-config|restore|restore-core|restore-config) local_core_action "$@" ;;
		force|'') update_core "$1" ;;
		*) return 1 ;;
	esac
}

exec 9>/var/lock/AdGuardHome-update.lock || exit 1
if ! flock -w 1 9; then
	printf '%s\n' 'A core update is already in progress. Wait for it to finish.'
	exit 2
fi
exec >/tmp/AdGuardHome_update.log 2>&1
printf 'running\n' >"$state_file" || exit 1
if [ "$1" = --background ]; then
	shift
	run_update "$@" </dev/null &
else
	run_update "$@"
fi
