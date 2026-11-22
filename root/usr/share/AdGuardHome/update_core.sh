#!/bin/sh

PATH="/usr/sbin:/usr/bin:/sbin:/bin"
state_file=/var/run/AdGuardHome-update.state
core_api_url="https://api.github.com/repos/AdguardTeam/AdGuardHome/releases/latest"
upload_root=/var/run/AdGuardHome-uploads
upload_limit=134217728

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
	output="$("$1" --version 8<&- 9>&- 2>/dev/null)" || return 1
	if [ "$2" = upload ]; then
		printf '%s\n' "$output" | sed -nE 's/^AdGuard Home,? version (v[0-9]+\.[0-9]+\.[0-9]+[[:alnum:].+~-]*)([, ].*)?$/\1/p' | head -n 1
		return
	fi
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

core_service_enabled() {
	case "$(uci get AdGuardHome.AdGuardHome.enabled 2>/dev/null)" in
		1|on|true|yes|enabled) return 0 ;;
	esac
	return 1
}

restart_if_enabled() {
	core_service_enabled || return 0
	printf '\nRestarting the AdGuard Home service...\n'
	(umask "$service_umask"; /etc/init.d/AdGuardHome restart 8<&- 9>&-) && wait_for_core
}

extract_core() {
	tar -xzOf "$1" ./AdGuardHome/AdGuardHome >"$2" 2>/dev/null ||
		tar -xzOf "$1" AdGuardHome/AdGuardHome >"$2" 2>/dev/null
}

install_core() {
	local current="$1" staged="$2" mode="$3"
	if [ "$(core_version "$binpath")" != "$current" ]; then
		printf '%s\n' 'The installed core changed. Try again.'
		return 1
	fi
	if [ -e "$binpath" ]; then
		if [ -z "$current" ]; then
			case "$mode" in force|upload) ;; *)
				printf '%s\n' 'The installed core is damaged. Use Force update or Upload core to repair it.'
				return 1 ;;
			esac
			regular_file "$binpath" || return 1
			current=damaged
		fi
		save_snapshot update "$current" both "$staged" || { printf '%s\n' 'Failed to save the core and YAML backup.'; return 1; }
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

elf_arch() {
	# 只比较 ELF 标识, 位数, 字节序及机器类型. 静态核心和动态 shell 的 ABI 标记可能不同.
	hexdump -v -n 20 -e '1/1 "%02x"' "$1" | cut -c1-12,37-40
}

upload_core() {
	local payload="$upload_dir/payload" expected="$1" actual staged size magic arch current version stage_path
	printf '%s\n' 'Validating the uploaded core...'
	if ! regular_file "$payload" || ! size="$(wc -c < "$payload")" || [ "$size" -le 0 ] || [ "$size" -gt "$upload_limit" ]; then
		printf '%s\n' 'The uploaded file is missing, empty, or exceeds 128 MiB.'
		return 1
	fi
	prepare_stage || return 1
	# 在写入大文件前登记两端的身份. Worker 被 SIGKILL 时, rpcd 也能找到对应的磁盘暂存目录.
	stage_path="$(readlink -f "$stage_dir")" && printf '%s\n' "$upload_dir" > "$stage_dir/.upload-owner" &&
		ln -s "$stage_path" "$upload_dir/.stage" || return 1
	staged="$stage_dir/core"
	if [ -n "$expected" ]; then
		# 校验和安装使用同一份私有副本, 已打开上传文件的 CGI 请求无法再改变其内容.
		(ulimit -f "$((upload_limit / 512))" && cp "$payload" "$stage_dir/upload") || return 1
		rm -f "$payload" || return 1
		payload="$stage_dir/upload"
		if [ "${#expected}" -ne 64 ] || ! actual="$(file_hash "$payload")" ||
		   [ "$actual" != "$(printf '%s' "$expected" | tr 'A-F' 'a-f')" ]; then
			printf '%s\n' 'Uploaded file SHA-256 verification failed.'
			return 1
		fi
		printf '%s\n' 'Uploaded file SHA-256 verified.'
	fi
	current="$(core_version "$binpath")"
	magic="$(hexdump -v -n 4 -e '1/1 "%02x"' "$payload")" || return 1
	# ash 的文件大小限制以 512 字节为单位, 在暂存文件增长前就限制空间.
	case "$magic" in
		7f454c46)
			if [ -n "$expected" ]; then
				mv "$payload" "$staged" || return 1
			else
				(ulimit -f "$((upload_limit / 512))" && cp "$payload" "$staged") || return 1
			fi ;;
		1f8b*)
			if ! (ulimit -f "$((upload_limit / 512))" && extract_core "$payload" "$staged") ||
			   [ ! -s "$staged" ] || [ "$(wc -c < "$staged")" -gt "$upload_limit" ]; then
				printf '%s\n' 'Failed to extract the core archive within the 128 MiB limit.'
				return 1
			fi ;;
		*) printf '%s\n' 'Select an AdGuard Home Linux binary or its official .tar.gz archive.'; return 1 ;;
	esac
	rm -f "$payload" || return 1
	arch="$(elf_arch "$staged")"
	if [ "${arch#7f454c46}" = "$arch" ] || [ "$arch" != "$(elf_arch /bin/sh)" ]; then
		printf '%s\n' 'The uploaded core does not match the device architecture.'
		return 1
	fi
	# 读取 Go 的主模块和目标系统, 在执行版本命令前识别传错的其他 Linux 程序.
	if ! LC_ALL=C strings "$staged" | awk -F '\t' '
		$1 == "path" && $2 == "github.com/AdguardTeam/AdGuardHome" { agh = 1 }
		$1 == "build" && $2 == "GOOS=linux" { linux = 1 }
		END { exit !(agh && linux) }
	'; then
		printf '%s\n' 'The uploaded file is not an AdGuard Home Linux core.'
		return 1
	fi
	chmod 755 "$staged" || return 1
	version="$(core_version "$staged" upload)"
	if [ -z "$version" ]; then
		printf '%s\n' 'The new core could not run or reported an unexpected version.'
		return 1
	fi
	printf 'Uploaded AdGuard Home version: %s\n' "$version"
	resolve_config || { printf '%s\n' 'The configured YAML file is not readable.'; return 1; }
	if [ -e "$configpath" ]; then
		check_snapshot_yaml "$staged" "$configpath" || return 1
	fi
	install_core "$current" "$staged" upload
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
	if ! extract_core "$work/core.tar.gz" "$staged"; then
		printf '%s\n' 'Failed to extract the core archive.'
		return 1
	fi
	chmod 755 "$staged" || return 1
	if [ "$(core_version "$staged")" != "$version" ]; then
		printf '%s\n' 'The new core could not run or reported an unexpected version.'
		return 1
	fi
	install_core "$current" "$staged" "$1"
}

cleanup() {
	local rc=$?
	trap - EXIT TERM INT HUP
	if [ "$restore_active" = 1 ]; then
		rollback_restore || [ "$outcome" = rollback_start_failed ] ||
			printf '%s\n' 'Rollback incomplete. The previous files are kept for the next attempt.'
	fi
	[ -z "$snapshot_tmp" ] || rm -rf "$snapshot_tmp"
	[ -z "$config_stage" ] || rm -rf "$config_stage"
	[ -z "$stage_dir" ] || rm -rf "$stage_dir"
	[ -z "$work" ] || rm -rf "$work"
	if [ -n "$upload_dir" ]; then
		rm -f "$upload_dir/payload"
		[ -d "$stage_dir" ] || rm -f "$upload_dir/.stage"
		rmdir "$upload_dir"
	fi
	printf '%s\n' "$outcome" >"$state_file"
	exit "$rc"
}

run_update() {
	outcome=failure work='' stage_dir='' snapshot_tmp='' config_stage='' upload_dir='' restore_active=0
	trap cleanup EXIT
	trap 'exit 1' TERM INT HUP
	case "$1" in
		upload)
			case "$2" in ??????) ;; *) return 1 ;; esac
			case "$2" in *[!a-zA-Z0-9]*) return 1 ;; esac
			private_dir "$upload_root" && private_dir "$upload_root/ready.$2" || return 1
			# 回收器通过目录锁区分仍在处理的任务和已经意外退出的任务.
			exec 8< "$upload_root/ready.$2" || return 1
			flock -n 8 || return 1
			upload_dir="$upload_root/ready.$2" ;;
		backup|backup-core|backup-config) outcome=backup_failed ;;
		restore|restore-core|restore-config|restore-both) outcome=restore_failed ;;
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
	if [ -e "$pending" ] || [ -L "$pending" ]; then
		if [ "$1" = delete ]; then
			outcome=rollback_failed
			printf '%s\n' 'Finish recovering the interrupted restore before deleting a backup.'
			return 1
		fi
		if ! rollback_restore; then
			[ "$outcome" = rollback_start_failed ] || printf '%s\n' 'Could not recover the interrupted restore.'
			return 1
		fi
	fi
	case "$1" in
		delete) delete_snapshot "$2" || { printf '%s\n' 'Failed to delete the selected backup.'; return 1; } ;;
		upload) upload_core "$3" ;;
		backup|backup-core|backup-config|restore|restore-core|restore-config|restore-both) local_core_action "$@" ;;
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
