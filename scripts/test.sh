#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

case "${1:-unit}" in
  unit)
    for script in scripts/*.sh tests/sdk/*.sh; do
      bash -n "$script"
    done
    node --test tests/*.test.js
    python3 -m unittest discover -s tests -p 'test_*.py' -v
    ;;
  browser)
    python3 tests/browser/test_verbose_checkbox.py
    ;;
  sdk)
    # 使用 SDK 构建出的工具, 避免维护额外的编译器和 apk 副本.
    if [[ -n "${SDK_DIR:-}" ]]; then
      export PATH="$SDK_DIR/staging_dir/hostpkg/bin:$SDK_DIR/staging_dir/host/bin:$PATH"
    fi
    python3 tests/sdk/test_split_packages.py
    bash tests/sdk/test_apk_rename.sh
    ;;
  *)
    echo "Usage: bash scripts/test.sh [unit|browser|sdk]" >&2
    exit 2
    ;;
esac
