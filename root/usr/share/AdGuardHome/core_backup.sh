# 这些操作由更新器在同一把 flock 内调用, 快照内容只对本机管理员可读.

regular_file() {
	[ -f "$1" ] && [ ! -L "$1" ]
}

private_dir() {
	[ -d "$1" ] && [ ! -L "$1" ] && ls -lnd "$1" | awk -v owner="$(id -u)" '
		$1 == "drwx------" && $3 == owner { ok = 1 }
		END { exit !ok }
	'
}

file_hash() {
	local value
	value="$(sha256sum < "$1")" || return 1
	printf '%s\n' "${value%% *}"
}

valid_snapshot_id() {
	case "$1" in
		[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]) return 0 ;;
		*) return 1 ;;
	esac
}

configured_paths() {
	workdir="$(uci get AdGuardHome.AdGuardHome.workdir 2>/dev/null)"
	workdir=${workdir:-/usr/bin/AdGuardHome}
	configpath="$(uci get AdGuardHome.AdGuardHome.configpath 2>/dev/null)"
	configpath=${configpath:-/etc/AdGuardHome.yaml}
	case "$configpath" in /*) ;; *) configpath="$workdir/$configpath" ;; esac
}

resolve_config() {
	configured_paths
	if [ -L "$configpath" ]; then
		configpath="$(readlink -f "$configpath")" || return 1
	fi
	case "$configpath" in
		"$binpath"|"$backup"|"$backup.meta"|"$history"|"$history"/*|"$pending"|"$pending"/*) return 1 ;;
	esac
	[ ! -e "$configpath" ] || { regular_file "$configpath" && [ ! "$configpath" -ef "$binpath" ]; }
}

check_snapshot_yaml() {
	local checker="$1" yaml="$2"
	if [ ! -e "$checker" ] && [ ! -L "$checker" ]; then
		printf '%s\n' 'YAML validation skipped: no core is installed.'
		return 0
	fi

	# 核心校验时可能迁移 YAML 并写入配置指定的日志, 只让它改写私有副本.
	prepare_work && cp "$yaml" "$work/check.yaml" || return 1
	if ! regular_file "$checker" || [ ! -x "$checker" ] ||
	   ! "$checker" --check-config -c "$work/check.yaml" -w "$workdir" -l /dev/null 9>&- >/dev/null 2>&1; then
		printf '%s\n' 'YAML configuration validation failed.'
		return 1
	fi
}

known_snapshot_files() {
	local dir="$1" file
	# 即使目录名恰好匹配, 发现陌生内容也保留整个目录.
	private_dir "$dir" || return 1
	for file in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
		[ -e "$file" ] || [ -L "$file" ] || continue
		case "${file##*/}" in .snapshot|core|config.yaml|meta) regular_file "$file" || return 1 ;; *) return 1 ;; esac
	done
	return 0
}

marked_snapshot() {
	regular_file "$1/.snapshot" && [ "$(cat "$1/.snapshot")" = 'AdGuard Home backup v1' ]
}

discard_partial_snapshot() {
	local dir="$1"
	marked_snapshot "$dir" && known_snapshot_files "$dir" || return 0
	rm -f "$dir/core" "$dir/config.yaml" "$dir/meta" && rm -f "$dir/.snapshot" && rmdir "$dir"
}

active_yaml_path() {
	local workdir configpath
	configured_paths
	if [ -e "$configpath" ]; then readlink -f "$configpath"; fi
}

inactive_snapshot_dir() {
	local resolved
	resolved="$(readlink -f "$1")" || return 1
	case "$active_yaml" in "$resolved"|"$resolved"/*) return 1 ;; esac
	return 0
}

clear_partial_snapshots() {
	local dir id active_yaml
	for dir in "$history"/.new.?????? "$history"/.*.expired; do
		[ -d "$dir" ] && [ ! -L "$dir" ] || continue
		case "${dir##*/}" in
			.new.??????) ;;
			*) id=${dir##*/.}; valid_snapshot_id "${id%.expired}" || continue ;;
		esac
		if [ -z "${active_yaml+x}" ]; then active_yaml="$(active_yaml_path)" || return 1; fi
		inactive_snapshot_dir "$dir" || continue
		discard_partial_snapshot "$dir" || return 1
	done
	return 0
}

valid_snapshot_meta() {
	local record
	regular_file "$1" && IFS= read -r record < "$1" &&
		printf '%s\n' "$record" | grep -Eq '^(manual|update) (v[^,[:space:]]+ [0-9a-f]{64} ([0-9a-f]{64}|-)|- - [0-9a-f]{64})$'
}

expire_snapshot() {
	local id="$1" part="${2:-both}" dir="$history/$1" expired="$history/.$1.expired"
	local origin version core_hash yaml_hash retained=''
	valid_snapshot_id "$id" && private_dir "$history" && known_snapshot_files "$dir" || return 1
	inactive_snapshot_dir "$dir" || return 1
	[ ! -e "$expired" ] && [ ! -L "$expired" ] || return 1
	if [ -e "$dir/.snapshot" ]; then
		marked_snapshot "$dir" || return 1
	else
		# 早期快照只有元数据, 验证归属后补标记以支持中断后的清理.
		valid_snapshot_meta "$dir/meta" && printf '%s\n' 'AdGuard Home backup v1' > "$dir/.snapshot" || return 1
	fi
	if [ "$part" != both ]; then
		valid_snapshot_meta "$dir/meta" && read -r origin version core_hash yaml_hash < "$dir/meta" && [ "$origin" = manual ] || return 1
		case "$part" in
			core)
				if [ "$yaml_hash" != - ] && regular_file "$dir/config.yaml"; then
					retained="manual - - $yaml_hash"
				fi ;;
			config.yaml)
				if [ "$core_hash" != - ] && regular_file "$dir/core"; then
					retained="manual $version $core_hash -"
				fi ;;
			*) return 1 ;;
		esac
	fi
	if [ -n "$retained" ]; then
		# 先原子发布保留项, 再释放另一项的数据. 同一编号仍可恢复原来的内容.
		if [ "$retained" != "$origin $version $core_hash $yaml_hash" ]; then
			snapshot_tmp="$(mktemp -d "$history/.new.XXXXXX")" || return 1
			printf '%s\n' 'AdGuard Home backup v1' > "$snapshot_tmp/.snapshot" &&
				printf '%s\n' "$retained" > "$snapshot_tmp/meta" &&
				mv -f "$snapshot_tmp/meta" "$dir/meta" || return 1
			discard_partial_snapshot "$snapshot_tmp" || return 1
			snapshot_tmp=''
		fi
		rm -f "$dir/$part"
		return $?
	fi
	mv "$dir" "$expired" && discard_partial_snapshot "$expired" && [ ! -e "$expired" ]
}

prune_snapshots() {
	local source="$1" keep="$2" part="${3:-both}" dir id count=0 ids='' leftovers='' ordered origin version core_hash yaml_hash active_yaml
	for dir in "$history"/[0-9]*; do
		id=${dir##*/}
		valid_snapshot_id "$id" && [ ! -L "$dir" ] && regular_file "$dir/meta" || continue
		read -r origin version core_hash yaml_hash < "$dir/meta" && [ "$origin" = "$source" ] || continue
		if [ "$part" != both ]; then
			regular_file "$dir/$part" && valid_snapshot_meta "$dir/meta" || continue
			# 若上次在元数据发布后中断, 补删已退出配额的文件.
			case "$part:$core_hash:$yaml_hash" in
				core:-:*|config.yaml:*:-)
					marked_snapshot "$dir" && leftovers="$leftovers $id"
					continue ;;
			esac
		fi
		ids="$ids $id"
		count=$((count + 1))
	done
	[ "$count" -gt "$keep" ] || [ -n "$leftovers" ] || return 0
	active_yaml="$(active_yaml_path)" || return 1
	for id in $leftovers; do expire_snapshot "$id" "$part" || return 1; done
	[ "$count" -gt "$keep" ] || return 0
	# 路由器校时可能使时间戳倒退, 按这一类备份的实际创建顺序淘汰.
	ordered="$(awk -v ids="$ids" '
		BEGIN { n = split(ids, keys, " "); for (i = 1; i <= n; i++) active[keys[i]] = 1 }
		$0 in active { sequence[++seen] = $0; delete active[$0] }
		END {
			for (i = 1; i <= n; i++) if (keys[i] in active) print keys[i]
			for (i = 1; i <= seen; i++) print sequence[i]
		}
	' "$history/.ids")" || return 1
	for id in $ordered; do
		[ "$count" -gt "$keep" ] || break
		expire_snapshot "$id" "$part" || return 1
		count=$((count - 1))
	done
	return 0
}

copy_snapshot_core() {
	local current="$1" hash="$2" dir
	# 只复用私有快照中的核心. 用户在原处改写运行文件时, 历史备份仍保留原字节.
	for dir in "$history"/[0-9]*; do
		valid_snapshot_id "${dir##*/}" && [ ! -L "$dir" ] && regular_file "$dir/meta" && regular_file "$dir/core" || continue
		grep -Fq " $hash " "$dir/meta" && [ "$(file_hash "$dir/core")" = "$hash" ] || continue
		ln "$dir/core" "$snapshot_tmp/core" 2>/dev/null && break
	done
	if [ ! -f "$snapshot_tmp/core" ]; then
		cp "$binpath" "$snapshot_tmp/core" && chmod 700 "$snapshot_tmp/core" || return 1
	fi
	if [ "$(file_hash "$snapshot_tmp/core")" != "$hash" ] || [ "$(core_version "$snapshot_tmp/core")" != "$current" ]; then
		printf '%s\n' 'The installed core changed. Try again.'
		return 1
	fi
}

save_snapshot() {
	local origin="$1" current="$2" part="${3:-both}" hash=- yaml_hash=- dir timestamp sequence id ledger last=0
	local groups file
	if [ "$part" != config ]; then
		[ -n "$current" ] || { printf '%s\n' 'No working core is available to back up.'; return 1; }
		printf 'Backing up core version: %s\n' "$current"
	fi
	if [ "$part" != core ]; then
		resolve_config && [ -s "$configpath" ] || { printf '%s\n' 'No readable YAML configuration is available to back up.'; return 1; }
	fi
	mkdir -p "$bindir" || return 1
	[ -d "$history" ] || mkdir -m 700 "$history" || return 1
	private_dir "$history" || return 1
	clear_partial_snapshots || return 1
	snapshot_tmp="$(mktemp -d "$history/.new.XXXXXX")" || return 1
	printf '%s\n' 'AdGuard Home backup v1' > "$snapshot_tmp/.snapshot" || return 1
	if [ "$part" != config ]; then
		hash="$(file_hash "$binpath")" && copy_snapshot_core "$current" "$hash" || return 1
	fi
	if [ "$part" != core ]; then
		cp "$configpath" "$snapshot_tmp/config.yaml" && chmod 600 "$snapshot_tmp/config.yaml" || return 1
		check_snapshot_yaml "$binpath" "$snapshot_tmp/config.yaml" || return 1
		yaml_hash="$(file_hash "$snapshot_tmp/config.yaml")" && [ "$yaml_hash" = "$(file_hash "$configpath")" ] || return 1
	fi
	if [ "$part" != config ] && [ "$hash" != "$(file_hash "$binpath")" ]; then
		printf '%s\n' 'The installed core changed. Try again.'
		return 1
	fi
	printf '%s %s %s %s\n' "$origin" "$current" "$hash" "$yaml_hash" > "$snapshot_tmp/meta" || return 1
	timestamp="$(date +%s)" || return 1
	timestamp="$(printf '%010d' "$timestamp")" || return 1
	ledger="$history/.ids"
	if [ -e "$ledger" ] || [ -L "$ledger" ]; then
		regular_file "$ledger" || return 1
	else
		touch "$ledger" || return 1
	fi
	for dir in "$history/$timestamp"-????; do
		valid_snapshot_id "${dir##*/}" && last=${dir##*-}
	done
	# 保留轻量的已分配编号. 自动清理或系统时钟回拨后, 旧恢复按钮不会指向另一份备份.
	sequence="$(awk -F- -v stamp="$timestamp" -v last="$last" '
		$1 == stamp && $2+0 > last+0 { last = $2 }
		END { print last+1 }
	' "$ledger")" || return 1
	[ "$sequence" -le 9999 ] || return 1
	id="$(printf '%s-%04d' "$timestamp" "$sequence")"
	valid_snapshot_id "$id" && printf '%s\n' "$id" >> "$ledger" || return 1
	mv "$snapshot_tmp" "$history/$id" || return 1
	snapshot_tmp=''
	if [ "$origin" = update ]; then
		prune_snapshots update 3 || printf '%s\n' 'Could not prune the oldest automatic backup.'
	else
		case "$part" in core) groups=core ;; config) groups=config.yaml ;; both) groups='core config.yaml' ;; esac
		for file in $groups; do
			prune_snapshots manual 5 "$file" || printf '%s\n' 'Could not prune the oldest manual backup.'
		done
	fi
	return 0
}

load_snapshot() {
	local id="$1" part="$2" dir meta record
	if [ "$id" = legacy ]; then
		[ "$part" != config ] || return 1
		source_core="$backup"
		source_yaml=''
		meta="$backup.meta"
		if [ ! -e "$backup.new" ] && [ ! -L "$backup.new" ] && regular_file "$backup.meta.new"; then
			meta="$backup.meta.new"
		fi
		regular_file "$source_core" && regular_file "$meta" || return 1
		read -r record < "$meta" && printf '%s\n' "$record" | grep -Eq '^v[^,[:space:]]+ [0-9a-f]{64}$' || return 1
		saved_version=${record% *}
		saved_core_hash=${record##* }
	else
		valid_snapshot_id "$id" && private_dir "$history" || return 1
		dir="$history/$id"
		private_dir "$dir" && valid_snapshot_meta "$dir/meta" || return 1
		IFS=' ' read -r _origin saved_version saved_core_hash saved_yaml_hash < "$dir/meta" || return 1
		if [ "$part" != config ] && [ "$saved_core_hash" != - ]; then
			source_core="$dir/core"
			regular_file "$source_core" || return 1
		fi
		if [ "$part" != core ] && [ "$saved_yaml_hash" != - ]; then
			source_yaml="$dir/config.yaml"
			regular_file "$source_yaml" || return 1
		fi
		[ -n "$source_core" ] || [ -n "$source_yaml" ] || return 1
	fi
}

delete_snapshot() {
	local id="$1" active_yaml file resolved source_core source_yaml saved_version saved_core_hash
	active_yaml="$(active_yaml_path)" || return 1
	if [ "$id" = legacy ]; then
		load_snapshot legacy core || return 1
		set -- "$backup" "$backup.meta"
		if [ ! -e "$backup.new" ] && [ ! -L "$backup.new" ]; then
			set -- "$@" "$backup.meta.new"
		fi
		for file do
			[ -e "$file" ] || [ -L "$file" ] || continue
			regular_file "$file" || return 1
			resolved="$(readlink -f "$file")" && [ "$resolved" != "$active_yaml" ] || return 1
		done
		# 先移除镜像即从时间线撤下, 中断最多留下小的旧元数据.
		rm -f "$1" || return 1
		shift
		rm -f "$@" || return 1
	else
		expire_snapshot "$id" || return 1
	fi
	outcome=deleted
	printf '%s\n' 'Backup deleted.'
}

stop_live_core() {
	local pid
	pid="$(ubus call service list '{"name":"AdGuardHome"}' 2>/dev/null | jsonfilter -e '@.AdGuardHome.instances.instance1.pid')"
	case "$pid" in ''|*[!0-9]*) return 0 ;; esac
	(umask "$service_umask"; /etc/init.d/AdGuardHome stop 9>&-)
}

prepare_rollback() {
	local dir="$stage_dir/pending" pid
	mkdir -m 700 "$dir" || return 1
	printf '%s\n' "${stage_dir##*/}" > "$dir/core-stage" || return 1
	if [ -z "$source_core" ]; then
		touch "$dir/keep-core" || return 1
	elif regular_file "$binpath"; then
		ln "$binpath" "$dir/previous-core" 2>/dev/null || cp -p "$binpath" "$dir/previous-core" || return 1
	else
		[ ! -e "$binpath" ] && touch "$dir/no-core" || return 1
	fi
	if [ -n "$source_yaml" ]; then
		printf '%s\n' "$configpath" > "$dir/config-path" || return 1
		printf '%s\n' "${config_stage##*/}" > "$dir/yaml-stage" || return 1
		if regular_file "$configpath"; then
			cp -p "$configpath" "$dir/previous-yaml" || return 1
		else
			[ ! -e "$configpath" ] && touch "$dir/no-yaml" || return 1
		fi
	fi
	if [ "$apply_service" = 1 ]; then
		pid="$(ubus call service list '{"name":"AdGuardHome"}' 2>/dev/null | jsonfilter -e '@.AdGuardHome.instances.instance1.pid')"
		case "$pid" in ''|*[!0-9]*) ;; *) touch "$dir/was-running" || return 1 ;; esac
	else
		touch "$dir/keep-service" || return 1
	fi
	mv "$dir" "$pending" || return 1
	restore_active=1
}

rollback_restore() {
	local cfg dir name restart=0
	[ -e "$pending" ] || { [ ! -L "$pending" ]; return; }
	private_dir "$pending" || return 1
	regular_file "$pending/keep-service" || stop_live_core || return 1
	if regular_file "$pending/previous-core"; then
		if [ ! "$pending/previous-core" -ef "$binpath" ]; then
			dir="$(mktemp -d "$bindir/.AdGuardHome.XXXXXX")" || return 1
			if { ln "$pending/previous-core" "$dir/core" 2>/dev/null || cp -p "$pending/previous-core" "$dir/core"; } &&
				mv -f "$dir/core" "$binpath"; then
				rmdir "$dir"
			else
				rm -rf "$dir"
				return 1
			fi
		fi
	elif regular_file "$pending/no-core"; then
		rm -f "$binpath" || return 1
	elif ! regular_file "$pending/keep-core"; then
		return 1
	fi
	if regular_file "$pending/config-path"; then
		IFS= read -r cfg < "$pending/config-path" || return 1
		if regular_file "$pending/previous-yaml"; then
			dir="$(mktemp -d "$(dirname "$cfg")/.AdGuardHome.XXXXXX")" || return 1
			if cp -p "$pending/previous-yaml" "$dir/config.yaml" && mv -f "$dir/config.yaml" "$cfg"; then
				rmdir "$dir"
			else
				rm -rf "$dir"
				return 1
			fi
		elif regular_file "$pending/no-yaml"; then
			rm -f "$cfg" || return 1
		else
			return 1
		fi
		if read -r name < "$pending/yaml-stage"; then
			case "$name" in .AdGuardHome.??????) rm -rf "$(dirname "$cfg")/$name" ;; esac
		fi
	fi
	if regular_file "$pending/was-running" && regular_file "$binpath"; then
		restart=1
	fi
	if read -r name < "$pending/core-stage"; then
		case "$name" in .AdGuardHome.??????) rm -rf "$bindir/$name" ;; esac
	fi
	# 先移除事务标记, 避免断电时将一半清理完的目录再次当作待恢复事务.
	dir="$(mktemp -d "$bindir/.AdGuardHome.XXXXXX")" || return 1
	mv "$pending" "$dir/completed" && rm -rf "$dir" || return 1
	restore_active=0
	if [ "$restart" = 1 ] && ! restart_if_enabled; then
		printf '%s\n' 'The previous files were restored, but the original service failed to start.'
	else
		printf '%s\n' 'The previous files were restored.'
	fi
}

restore_snapshot() {
	local source_core='' source_yaml='' saved_core_hash saved_yaml_hash saved_version _origin apply_service=1
	local checker="$binpath"
	load_snapshot "$1" "$2" || { printf '%s\n' 'The selected backup is unavailable.'; return 1; }
	prepare_stage || return 1
	if [ -n "$source_core" ]; then
		printf 'Restoring core version: %s\n' "$saved_version"
		cp "$source_core" "$stage_dir/core" || return 1
		[ "$(file_hash "$stage_dir/core")" = "$saved_core_hash" ] || { printf '%s\n' 'Local core backup checksum verification failed.'; return 1; }
		chmod 755 "$stage_dir/core" || return 1
		[ "$(core_version "$stage_dir/core")" = "$saved_version" ] || { printf '%s\n' 'The backup could not run or reported an unexpected version.'; return 1; }
		checker="$stage_dir/core"
	elif [ ! -x "$binpath" ] || ! regular_file "$binpath"; then
		# 核心缺失时 init 会自动下载安装, 仅还原配置须保留正在运行的进程.
		apply_service=0
	fi
	if [ -n "$source_yaml" ]; then
		resolve_config && mkdir -p "$(dirname "$configpath")" || return 1
		config_stage="$(mktemp -d "$(dirname "$configpath")/.AdGuardHome.XXXXXX")" || return 1
		cp "$source_yaml" "$config_stage/config.yaml" && chmod 600 "$config_stage/config.yaml" || return 1
		[ "$(file_hash "$config_stage/config.yaml")" = "$saved_yaml_hash" ] || { printf '%s\n' 'YAML backup checksum verification failed.'; return 1; }
		check_snapshot_yaml "$checker" "$config_stage/config.yaml" || return 1
	fi
	prepare_rollback || return 1
	if [ "$apply_service" = 1 ]; then
		stop_live_core || return 1
	fi
	if [ -n "$source_core" ]; then
		mv -f "$stage_dir/core" "$binpath" || return 1
	fi
	if [ -n "$source_yaml" ]; then
		mv -f "$config_stage/config.yaml" "$configpath" || return 1
	fi
	if [ "$apply_service" = 1 ] && ! restart_if_enabled; then
		outcome=restore_start_failed
		printf '%s\n' 'The restored service failed to start. Reverting to the previous files.'
		return 1
	fi
	mv "$pending" "$stage_dir/completed" || return 1
	restore_active=0
	outcome=restored
	printf '%s\n' 'Local backup restored.'
}

local_core_action() {
	local op="$1" part="${1#*-}" current=- success failure
	case "$op" in backup|restore) part=both ;; esac
	case "$op" in
		restore|restore-core|restore-config) restore_snapshot "$2" "$part"; return $? ;;
	esac
	case "$part" in
		core)   success='Core backup saved.'; failure='Failed to save the core backup.' ;;
		config) success='YAML backup saved.'; failure='Failed to save the YAML backup.' ;;
		both)   success='Core and YAML backup saved.'; failure='Failed to save the core and YAML backup.' ;;
	esac
	[ "$part" = config ] || current="$(core_version "$binpath")"
	save_snapshot manual "$current" "$part" || { printf '%s\n' "$failure"; return 1; }
	outcome=backed_up
	printf '%s\n' "$success"
}
