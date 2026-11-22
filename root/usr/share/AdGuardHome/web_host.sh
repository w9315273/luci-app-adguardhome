#!/bin/sh

core=$1
config=$2

read_host() {
	awk -v wrapped="$1" '
		function host(value, port,    quote) {
			sub(/^[ \t]+/, "", value)
			sub(/[ \t]+#.*$/, "", value)
			sub(/[ \t\r]+$/, "", value)
			quote = substr(value, 1, 1)
			if (quote == "\047" || quote == "\"") {
				if (substr(value, length(value)) != quote) return ""
				value = substr(value, 2, length(value)-2)
				if (quote == "\047") gsub(/\047\047/, "\047", value)
			}
			if (port && !sub(/:[0-9]+$/, "", value)) return ""
			if (value ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) return value
			if (value ~ /^\[[[:xdigit:]:.]+(%[^][\\]+)?\]$/ && index(value, ":")) return value
			if (!port && value ~ /^[[:xdigit:]:.]+(%[^][\\]+)?$/ && index(value, ":")) return "[" value "]"
			return ""
		}
		{ sub(/\r$/, "") }
		!wrapped {
			if (/^[ \t]*(#|$)/) next
			if (!http) { if ($0 != "http:") exit; http = 1; next }
			if (!/^  /) exit
			if (sub(/^  address: /, "")) { result = host($0, 1); exit }
			if (/^ +[[:alnum:]_]+:( [[:alnum:]_.-]+)?$/ || /^ +- (GET|POST) \/[[:alnum:]_.{}\/-]+$/) next
			exit
		}
		/^[^ ]/ {
			if (/^schema_version: [1-9][0-9]*$/) migrated = 1
			source = ($0 == "source:" || $0 == "source: {}")
			if (source) mapping = 1
			http = 0
			next
		}
		source {
			indent = match($0, /[^ ]/) - 1
			if (indent < 1) next
			if (!root_indent) root_indent = indent
			line = substr($0, indent + 1)
			if (indent == root_indent) {
				if (line ~ /^-([ \t]|$)/) invalid = 1
				http = (line == "http:")
				http_indent = 0
				if (line ~ /^http:/ && !http && line != "http: {}") invalid = 1
				if (sub(/^bind_host: */, "", line)) { legacy = host(line, 0); has_legacy = 1 }
			} else if (http) {
				if (!http_indent) http_indent = indent
				if (indent == http_indent && sub(/^address: */, "", line)) { result = host(line, 1); has_address = 1 }
			}
		}
		END {
			if (wrapped && (!migrated || !mapping || invalid)) exit 1
			if (wrapped && !has_address) result = has_legacy ? legacy : "0.0.0.0"
			if (!result) exit 1
			print result
		}
	' "$2"
}

if read_host 0 "$config"; then
	exit 0
fi

umask 077
work=$(mktemp -d /tmp/AdGuardHome-web.XXXXXX) || exit 1
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
probe="$work/config.yaml"
awk '
	function start() { if (!started) { print "---\nsource:"; started = 1 } }
	NR == 1 { sub(/^\357\273\277/, "") }
	!started && /^%/ { print; next }
	!started && /^[ \t\r]*(#|$)/ { next }
	/^\.\.\.([ \t\r]|$)/ { exit }
	/^---([ \t\r]|$)/ {
		if (started) exit
		start()
		sub(/^---[ \t]*/, "")
	}
	{ start(); print "  " $0 }
	END { if (!started) exit 1 }
' "$config" >"$probe" || exit 1
"$core" --check-config -c "$probe" -w "$work" >/dev/null 2>&1 || exit 1
read_host 1 "$probe"
