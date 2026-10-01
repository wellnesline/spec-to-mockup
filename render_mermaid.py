#!/usr/bin/env python3
"""sitemap render (Mermaid 版): screens.yaml → sitemap.md (Mermaid flowchart 埋込).

   Mermaid に pivot した理由:
     - excalidraw は ホワイトボードツールで sitemap(フロー図) 用途には不向き
     - 「scope 矩形 はみ出し / 矢印交差」 は excalidraw 固有の弱み
     - Mermaid は 自動レイアウト + subgraph(swimlane) + 矢印 routing 最適化 を 標準サポート
     - markdown 埋込 = git diff 可、 人間が VS Code preview で 即見える
     - 画像埋込は不可だが、 ノードクリックで URL 別タブで補完(`click NodeID "url"`)

   使い方:
     python render_mermaid.py <screens_yaml> <output_md>
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

ROOT = Path(__file__).resolve().parent
DEFAULT_MOCKUP_DIR = ROOT / "mockups"


SCOPE_META = {
    "global":         {"label": "🟦 global scope",         "color": "#eef2ff"},
    "project":        {"label": "🟢 project scope",        "color": "#ecfdf5"},
    "per_project":    {"label": "🟧 per-project(設定)", "color": "#fffbeb"},
    "per_item":      {"label": "🟪 per-item",   "color": "#fdf2f8"},
    "global_utility": {"label": "🟦 global utility",        "color": "#eef2ff"},
    "error":          {"label": "🟦 global error / auth",    "color": "#eef2ff"},
}

SCOPE_ORDER = ["global", "project", "per_project", "per_item", "global_utility", "error"]


def safe_id(s: str) -> str:
    """Mermaid node id 用に kebab-case を 安全文字列に(ハイフンは Mermaid で許容、 そのまま)."""
    return s.replace(" ", "_")


def render_mermaid(screens_yaml: Path, output_md: Path) -> dict:
    sb = yaml.safe_load(screens_yaml.read_text(encoding="utf-8"))
    screens = sb["screens"]

    # scope ごとに screens を group
    by_scope: dict[str, list[dict]] = {s: [] for s in SCOPE_ORDER}
    for screen in screens:
        scope = screen.get("scope", "global")
        if scope in by_scope:
            by_scope[scope].append(screen)

    # Mermaid flowchart 構築
    lines: list[str] = []
    lines.append("```mermaid")
    lines.append("flowchart TB")
    lines.append("    %% 自動生成: scripts/sitemap_pipeline/render_mermaid.py")
    lines.append("")

    # ノード style クラス定義
    lines.append("    classDef designedNode fill:#e0f2fe,stroke:#1B3A5C,stroke-width:2px,color:#0c4a6e")
    lines.append("    classDef missingNode fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px,stroke-dasharray:4 4,color:#475569")
    lines.append("")

    # subgraph 単位で scope を 出力
    for scope_name in SCOPE_ORDER:
        meta = SCOPE_META[scope_name]
        screens_in_scope = by_scope[scope_name]
        if not screens_in_scope:
            continue
        # subgraph
        lines.append(f'    subgraph {scope_name}["{meta["label"]}"]')
        lines.append("        direction LR")
        for screen in screens_in_scope:
            sid = safe_id(screen["id"])
            name = screen.get("name", "(no name)")
            status_icon = "✅" if screen.get("status") == "designed" else "🆕"
            # Mermaid ノード: id["表示名 (改行) サブ情報"]
            label = f"{status_icon} {name}"
            # 改行は Mermaid では `<br/>` で
            lines.append(f'        {sid}["{label}<br/><small>{screen["id"]}</small>"]')
        lines.append("    end")
        lines.append("")

    # edges を 全部出す
    lines.append("    %% Edges")
    for screen in screens:
        from_id = safe_id(screen["id"])
        for edge in screen.get("edges", []) or []:
            to_id = safe_id(edge.get("to", ""))
            if not to_id:
                continue
            style = edge.get("style", "solid")
            label = edge.get("label", "") or ""
            if style == "dashed":
                if label:
                    lines.append(f'    {from_id} -. "{label}" .-> {to_id}')
                else:
                    lines.append(f'    {from_id} -.-> {to_id}')
            else:
                if label:
                    lines.append(f'    {from_id} -- "{label}" --> {to_id}')
                else:
                    lines.append(f'    {from_id} --> {to_id}')
    lines.append("")

    # class 適用(designed / missing で 色分け)
    designed_ids = [safe_id(s["id"]) for s in screens if s.get("status") == "designed"]
    missing_ids = [safe_id(s["id"]) for s in screens if s.get("status") != "designed"]
    if designed_ids:
        lines.append(f"    class {','.join(designed_ids)} designedNode")
    if missing_ids:
        lines.append(f"    class {','.join(missing_ids)} missingNode")
    lines.append("")

    # click イベント(designed screen のみ、 image パスを 開く)
    lines.append("    %% Click events (designed screens のみ、 画像 URL を 別タブで開く)")
    for screen in screens:
        if screen.get("status") == "designed" and screen.get("image"):
            sid = safe_id(screen["id"])
            img_path = screen["image"]
            lines.append(f'    click {sid} "{img_path}" "{screen.get("name", "")}"')

    lines.append("```")

    # markdown wrapper
    md_body = "\n".join(lines)
    md_full = f"""# サンプルWebUI 画面遷移図(Mermaid 版)

> 自動生成: `scripts/sitemap_pipeline/render_mermaid.py`
> 入力: `{screens_yaml.resolve().relative_to(ROOT) if screens_yaml.resolve().is_relative_to(ROOT) else screens_yaml.name}`
> Mermaid フローチャートで scope を swimlane 表現、 自動レイアウト + 矢印交差最適化。

## 凡例

- ✅ designed = 採用済(背景 light blue + 実線枠)
- 🆕 missing = 抜け候補(背景 light gray + 点線枠)
- 実線矢印 = 主要動線
- 点線矢印 = 抜け候補への動線 or 補助

## 画面一覧(クリックで mockup 画像を 別タブで開く)

{md_body}

## scope 別 集計

| Scope | 画面数 | 内訳(designed / missing) |
|---|---|---|
"""
    for scope_name in SCOPE_ORDER:
        sl = [s for s in screens if s.get("scope") == scope_name]
        if not sl:
            continue
        designed_n = sum(1 for s in sl if s.get("status") == "designed")
        missing_n = len(sl) - designed_n
        meta = SCOPE_META[scope_name]
        md_full += f"| {meta['label']} | {len(sl)} | designed: {designed_n} / missing: {missing_n} |\n"

    md_full += f"\n**合計**: {len(screens)} 画面(designed: {sum(1 for s in screens if s.get('status') == 'designed')} / missing: {sum(1 for s in screens if s.get('status') != 'designed')})、 edges: {sum(len(s.get('edges') or []) for s in screens)} 本\n"

    output_md.write_text(md_full, encoding="utf-8")

    stats = {
        "screens_total": len(screens),
        "screens_designed": sum(1 for s in screens if s.get("status") == "designed"),
        "screens_missing": sum(1 for s in screens if s.get("status") != "designed"),
        "edges_total": sum(len(s.get("edges") or []) for s in screens),
        "output_bytes": output_md.stat().st_size,
        "output_lines": md_full.count("\n"),
    }
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="screens.yaml → sitemap.md (Mermaid)")
    ap.add_argument("screens_yaml", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args(argv)

    if not args.screens_yaml.exists():
        print(f"ERROR: {args.screens_yaml} not found", file=sys.stderr)
        return 1

    stats = render_mermaid(args.screens_yaml, args.output)
    print(f"Saved: {args.output}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
