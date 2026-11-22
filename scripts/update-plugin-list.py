import argparse
import json
import re
from html import escape
from pathlib import Path


DOCS = Path(__file__).resolve().parent.parent / "docs"
TITLES = {"zh": "我的插件列表", "en": "My plugin list"}
STAR_LABELS = {"zh": "GitHub 星数", "en": "GitHub stars"}
BLOCK = re.compile(
    r"^<!-- plugin-list: (?P<lang>zh|en) (?P<repo>\S+) -->(?P<newline>\r?\n)"
    r"(?P<body>.*?)^<!-- /plugin-list -->\r?$",
    re.MULTILINE | re.DOTALL,
)


def render_table(plugins, lang, current_repo):
    rows = ["<table>", f'  <tr><th colspan="3">{TITLES[lang]}</th></tr>']
    for plugin in sorted(plugins, key=lambda item: item["repo"] != current_repo):
        repo = escape(plugin["repo"])
        name = escape(plugin["name"])
        badge_url = f"https://img.shields.io/github/stars/{repo}?style=flat&amp;label=%E2%98%85&amp;color=57606a"
        badge = f'<img src="{badge_url}" height="16" alt="{name} · {STAR_LABELS[lang]}">'
        if plugin["repo"] != current_repo:
            name = f'<a href="https://github.com/{repo}">{name}</a>'
        rows.extend([
            '  <tr valign="middle">',
            f'    <td>{badge}</td>',
            f"    <td><strong>{name}</strong></td>",
            f"    <td>{escape(plugin[lang])}</td>",
            "  </tr>",
        ])
    return [*rows, "</table>"]


def update_readme(path, plugins):
    content = path.read_bytes().decode("utf-8")
    match = BLOCK.search(content)
    if not match:
        raise ValueError(f"{path}: 缺少插件列表标记, 请查看 --help")
    if not any(plugin["repo"] == match["repo"] for plugin in plugins):
        raise ValueError(f"{path}: 插件清单中没有 {match['repo']}")
    table = match["newline"].join(render_table(plugins, match["lang"], match["repo"]))
    updated = content[:match.start("body")] + table + match["newline"] + content[match.end("body"):]
    if updated != content:
        path.write_bytes(updated.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="从 docs/plugins.json 更新 README 中的插件列表.",
        epilog="复用时, 在目标 README 中单独写两行标记, "
        "例如 <!-- plugin-list: en w9315273/luci-app-pulse --> 和 <!-- /plugin-list -->, "
        "再把 README 路径传给脚本. 中文使用 zh.",
    )
    parser.add_argument("readmes", nargs="*", type=Path, help="默认更新本仓库的中英文 README")
    args = parser.parse_args()
    try:
        plugins = json.loads((DOCS / "plugins.json").read_text(encoding="utf-8"))
        for path in args.readmes or [DOCS / "README.md", DOCS / "README.en.md"]:
            update_readme(path, plugins)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
