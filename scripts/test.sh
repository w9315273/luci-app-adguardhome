#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

export PYTHONDONTWRITEBYTECODE=1

case "${1:-unit}" in
  unit)
    for script in scripts/*.sh tests/sdk/*.sh; do
      bash -n "$script"
    done
    printf '\n%s\n' '运行前端回归测试...'
    node --test --test-reporter=./tests/reporter.cjs tests/*.test.js
    printf '\n%s\n' '运行服务与 DNS 回归测试...'
    python3 tests/run-python.py --label '服务与 DNS ' discover tests
    ;;
  browser)
    python3 tests/run-python.py --label '详细日志开关的默认值, 保存, 失败恢复和只读状态' command python3 tests/browser/test_verbose_checkbox.py
    python3 tests/run-python.py --label '备份时间线的操作权限, 恢复范围及所选记录' command python3 tests/browser/test_backup_timeline.py
    ;;
  sdk)
    # 使用 SDK 构建出的工具, 避免维护额外的编译器和 apk 副本.
    if [[ -n "${SDK_DIR:-}" ]]; then
      export PATH="$SDK_DIR/staging_dir/hostpkg/bin:$SDK_DIR/staging_dir/host/bin:$PATH"
    fi
    python3 tests/run-python.py --label 'SDK 分包, 翻译编译, 下载失败处理及产物收集' command python3 tests/sdk/test_split_packages.py
    python3 tests/run-python.py --label 'APK 包名迁移, 重装及升级时保留用户配置' command bash tests/sdk/test_apk_rename.sh
    ;;
  *)
    echo "Usage: bash scripts/test.sh [unit|browser|sdk]" >&2
    exit 2
    ;;
esac
