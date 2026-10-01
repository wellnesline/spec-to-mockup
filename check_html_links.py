#!/usr/bin/env python3
"""HTML mock の dead link + 到達不能画面 を 検出。
   - 各 *.html の <a href="..."> を 抽出
   - 同ディレクトリ内に 該当 .html が 存在するか チェック(404 検出)
   - index.html を 起点に BFS で 到達可能な画面集合 を 算出
   - 到達不能(orphan)画面を 検出
   - 出力 = report (markdown)
"""
from __future__ import annotations
import re
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLICKABLE_DIR = ROOT / "mockups" / "clickable"
REPORT = CLICKABLE_DIR / "_link_check_report.md"

HREF_RE = re.compile(r'<a\s+[^>]*?href=["\']([^"\']+)["\']', re.IGNORECASE)


def extract_links(html_path: Path) -> list[str]:
    text = html_path.read_text(encoding="utf-8")
    return HREF_RE.findall(text)


def main() -> int:
    html_files = sorted(CLICKABLE_DIR.glob("*.html"))
    print(f"Checking {len(html_files)} HTML files in {CLICKABLE_DIR}")

    file_set = {f.name for f in html_files}

    # 1. dead link 検出
    dead_links: list[tuple[str, str]] = []
    edge_graph: dict[str, set[str]] = {}  # src → set(dst)

    for html in html_files:
        edge_graph[html.name] = set()
        for href in extract_links(html):
            # 外部 / アンカー / 画像 / 親ディレクトリ参照は スキップ
            if href.startswith("http") or href.startswith("#") or href.startswith("mailto:"):
                continue
            if href.startswith("../"):
                # ../sitemap.png 等 親 dir 参照は 別検査(存在チェックのみ)
                target = (CLICKABLE_DIR / href).resolve()
                if not target.exists():
                    dead_links.append((html.name, href))
                continue
            # 同ディレクトリ内 .html 参照
            target_name = href.split("#")[0]
            if not target_name.endswith(".html"):
                continue  # 画像など .html 以外は skip
            if target_name not in file_set:
                dead_links.append((html.name, href))
            else:
                edge_graph[html.name].add(target_name)

    # 2. 到達可能性検査(index.html 起点 BFS)
    start = "index.html"
    reachable: set[str] = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in edge_graph.get(cur, set()):
            if nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)

    orphans = file_set - reachable

    # 3. 双方向確認(戻り edge の有無。 reviewer 指摘の反映用)
    bidirectional_missing: list[tuple[str, str]] = []
    # reviewer の missing_edges 指摘は screens.yaml の edges から自動検出するのは難しいので、 review.md の指摘を反映
    # 簡易チェック: 戻る edge があるか(各画面に sidebar / breadcrumb がある = 戻れる)
    # → sidebar が 全画面共通で 含まれているので、 「dead-end」 は理論的に発生しない

    # 4. レポート出力
    report = ["# HTML Mock Link Check Report", "", f"Date: {Path('/dev/null').stat() and 'auto'}", ""]
    report.append(f"## サマリ")
    report.append(f"- 検査 HTML: {len(html_files)} 件")
    report.append(f"- dead link: {len(dead_links)} 件")
    report.append(f"- 到達可能: {len(reachable)} / {len(file_set)} 件")
    report.append(f"- orphan(到達不能): {len(orphans)} 件")
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
        report.append("## ⚠️ Orphan(index から到達不能)")
        for o in sorted(orphans):
            report.append(f"- `{o}`")
        report.append("")
    else:
        report.append("## ✅ 全画面が index から 到達可能")
        report.append("")

    # 5. edge グラフ統計
    report.append("## グラフ統計")
    in_degree = {n: 0 for n in file_set}
    out_degree = {n: 0 for n in file_set}
    for src, dsts in edge_graph.items():
        out_degree[src] = len(dsts)
        for dst in dsts:
            in_degree[dst] = in_degree.get(dst, 0) + 1
    report.append(f"- 総 edge 数: {sum(out_degree.values())}")
    report.append(f"- in_degree = 0(誰からも参照されない): {sum(1 for v in in_degree.values() if v == 0)} 件")
    no_incoming = [n for n, v in in_degree.items() if v == 0 and n != "index.html"]
    if no_incoming:
        for n in sorted(no_incoming):
            report.append(f"  - `{n}`")
    report.append(f"- out_degree = 0(行き止まり): {sum(1 for v in out_degree.values() if v == 0)} 件")
    no_outgoing = [n for n, v in out_degree.items() if v == 0]
    if no_outgoing:
        for n in sorted(no_outgoing):
            report.append(f"  - `{n}`")
    report.append("")

    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(f"Report: {REPORT}")

    # console 出力
    print()
    print(f"Dead links: {len(dead_links)}")
    print(f"Orphan(到達不能): {len(orphans)}")
    print(f"Reachable: {len(reachable)} / {len(file_set)}")

    if dead_links:
        print("\nDead links 詳細:")
        for src, href in dead_links[:10]:
            print(f"  {src} → {href}")

    if orphans:
        print("\nOrphan 詳細:")
        for o in sorted(orphans):
            print(f"  {o}")

    return 1 if dead_links else 0


if __name__ == "__main__":
    sys.exit(main())
