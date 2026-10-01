#!/usr/bin/env python3
"""HTML mock の 静的 audit (shell.js pivot 後の縮小版)。

shell.js が runtime で sidebar / canonical-breadcrumb / scope-sub-nav を
動的注入するので、 HTML 内に これらが「文字列として」 存在するかは チェック対象外。
本 audit は

  - dead link (リンク先 HTML が存在しない)
  - orphan (projects-list 起点 BFS で 到達不能)
  - shell.js + screens-data.js + data-screen-id の 3点セットが 揃っているか
  - data-screen-id が screens.yaml に 登録された id か

の 4 軸のみ。 sidebar / chrome の 不整合は shell.js の 同一ソース注入で
構造的に発生不能なので 静的 audit から外した。
"""
from __future__ import annotations
import re
import sys
from collections import deque, defaultdict
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    print("PyYAML が必要")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent
CLICKABLE_DIR = ROOT / "mockups" / "clickable"
SCREENS_YAML = ROOT / "mockups" / "screens.yaml"
REPORT = CLICKABLE_DIR / "_link_audit_full.md"

_DATA = yaml.safe_load(SCREENS_YAML.read_text(encoding="utf-8"))
_SCREENS_BY_ID = {s["id"]: s for s in _DATA["screens"]}
VALID_IDS = set(_SCREENS_BY_ID.keys()) | {"index"}
VALID_TARGETS = {f"{i}.html" for i in VALID_IDS}

A_HREF_RE = re.compile(r'<a\s+[^>]*?href=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
BODY_OPEN_RE = re.compile(r'<body\b[^>]*>', re.IGNORECASE)
DATA_SID_RE = re.compile(r'data-screen-id="([^"]+)"', re.IGNORECASE)


def extract_anchors(html: str) -> list[str]:
    return A_HREF_RE.findall(html)


def main() -> int:
    html_files = sorted([f for f in CLICKABLE_DIR.glob("*.html") if f.name != "index.html"])
    print(f"Auditing {len(html_files)} HTML mocks in {CLICKABLE_DIR}")

    dead_links: list[tuple[str, str]] = []
    edge_graph: dict[str, set[str]] = defaultdict(set)
    shell_issues: list[tuple[str, str]] = []

    for html in html_files:
        text = html.read_text(encoding="utf-8")

        # shell 構成 3 点セット
        if 'src="shell.js"' not in text:
            shell_issues.append((html.name, "shell.js script 不在"))
        if 'src="screens-data.js"' not in text:
            shell_issues.append((html.name, "screens-data.js script 不在"))
        m = BODY_OPEN_RE.search(text)
        if not m:
            shell_issues.append((html.name, "<body> 不在"))
        else:
            sid_m = DATA_SID_RE.search(m.group(0))
            if not sid_m:
                shell_issues.append((html.name, "<body data-screen-id> 不在"))
            elif sid_m.group(1) not in VALID_IDS:
                shell_issues.append((html.name, f"data-screen-id='{sid_m.group(1)}' が screens.yaml に未登録"))
            elif sid_m.group(1) != html.stem:
                shell_issues.append(
                    (html.name, f"data-screen-id='{sid_m.group(1)}' != filename stem '{html.stem}'")
                )

        # dead link / edge graph
        for href in extract_anchors(text):
            if href.startswith(("#", "http", "mailto:", "javascript:")):
                continue
            if href.startswith("../"):
                target = (CLICKABLE_DIR / href).resolve()
                if not target.exists():
                    dead_links.append((html.name, href))
                continue
            target_name = href.split("#")[0]
            if not target_name.endswith(".html"):
                continue
            if target_name not in VALID_TARGETS:
                dead_links.append((html.name, href))
            else:
                edge_graph[html.name].add(target_name)

    # 注: shell.js も リンクを生成するため、 HTML 内 anchor だけでは
    # sidebar/breadcrumb/sub-nav のリンクが 拾えない。 これらは shell.js が
    # screens.yaml から 静的に決め打ちで生成しているため、 audit 不要 (構造的に正しい)。
    # 補完: shell.js が必ず生成する link を edge_graph に 追加して orphan 検出。
    SHELL_INJECTED_FROM_ANY = {
        "dashboard-kpi.html",
        "projects-list.html",
        "asset-library.html",
        "account-settings.html",
        "index.html",
    }
    for f in [h.name for h in html_files]:
        screen = _SCREENS_BY_ID.get(Path(f).stem, {})
        if screen.get("chrome_layout") == "modal_fullscreen":
            continue
        if screen.get("scope") == "error":
            continue
        edge_graph[f].update(SHELL_INJECTED_FROM_ANY)
        # scope_sub_nav 経由のリンクも shell.js が 生成
        scope = screen.get("scope")
        scope_sub_nav = _DATA.get("scope_sub_nav", {})
        if scope in scope_sub_nav:
            for it in scope_sub_nav[scope]["items"]:
                edge_graph[f].add(f"{it['id']}.html")
        # parent_chain も shell.js が breadcrumb link 化
        for pid in screen.get("parent_chain") or []:
            edge_graph[f].add(f"{pid}.html")

    # orphan (projects-list 起点 BFS)
    start = "projects-list.html"
    reachable: set[str] = {start, "index.html"}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in edge_graph.get(cur, set()):
            if nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)
    all_files = {f.name for f in html_files}
    orphans = (all_files - reachable) - {"login.html", "error-page.html", "index.html"}

    # report
    report = ["# HTML Mock 静的 Audit (shell.js form)", ""]
    report.append("## サマリ")
    report.append(f"- 検査 HTML: {len(html_files)} 件(index.html 除外)")
    report.append(f"- shell 構成 不整合: {len(shell_issues)} 件")
    report.append(f"- dead link: {len(dead_links)} 件")
    report.append(f"- orphan: {len(orphans)} 件")
    report.append("")
    if shell_issues:
        report.append("## ⛔ shell 構成 不整合")
        for f, msg in shell_issues:
            report.append(f"- `{f}`: {msg}")
        report.append("")
    else:
        report.append("## ✅ 全 HTML が shell 構成 (body data-screen-id + screens-data.js + shell.js) 揃い")
        report.append("")
    if dead_links:
        report.append("## ⛔ Dead Links")
        for src, href in dead_links:
            report.append(f"- `{src}` → `{href}`")
        report.append("")
    else:
        report.append("## ✅ Dead Links なし")
        report.append("")
    if orphans:
        report.append("## ⚠️ Orphan (projects-list から 到達不能)")
        for o in sorted(orphans):
            report.append(f"- `{o}`")
        report.append("")
    else:
        report.append("## ✅ 全画面が projects-list から 到達可能")
        report.append("")

    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(f"Report: {REPORT}")
    print(f"shell 不整合: {len(shell_issues)}")
    print(f"Dead links: {len(dead_links)}")
    print(f"Orphan: {len(orphans)}")

    critical = len(shell_issues) + len(dead_links) + len(orphans)
    return 1 if critical > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
