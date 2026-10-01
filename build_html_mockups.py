#!/usr/bin/env python3
"""全画面分の HTML モック を 1 つの共通テンプレートで 自動生成。
   入力: screens.yaml + 採用画像 / 抜け候補画像
   出力: mockups/clickable/<screen_id>.html × 24

   各 HTML:
     - Tailwind CDN + daisyUI CDN + Noto Sans JP
     - 共通サイドバー(固定 5 リンク)
     - Topbar(breadcrumb + screen name + scope badge)
     - Main: 大きな mockup 画像 + 下に edges のナビゲーションボタン群
     - 戻る / ホーム / 凡例
"""
from __future__ import annotations
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

ROOT = Path(__file__).resolve().parent
MOCKUP_DIR = ROOT / "mockups"
CLICKABLE_DIR = MOCKUP_DIR / "clickable"
SCREENS_YAML = MOCKUP_DIR / "screens.yaml"


SCOPE_META = {
    "global":         {"label": "global",          "color": "indigo",  "icon": "🟦"},
    "project":        {"label": "project",         "color": "emerald", "icon": "🟢"},
    "per_project":    {"label": "per-project",     "color": "amber",   "icon": "🟧"},
    "per_item":      {"label": "per-item",       "color": "pink",    "icon": "🟪"},
    "global_utility": {"label": "global utility",  "color": "indigo",  "icon": "🟦"},
    "error":          {"label": "global error",    "color": "indigo",  "icon": "🟦"},
}


def html_template(screen: dict, all_screens: dict[str, dict], image_url: str | None) -> str:
    sid = screen["id"]
    name = screen.get("name", "(no name)")
    scope = screen.get("scope", "global")
    scope_meta = SCOPE_META[scope]
    status = screen.get("status", "designed")
    status_badge = (
        '<span class="badge bg-emerald-100 text-emerald-800 border-0">✅ designed</span>'
        if status == "designed"
        else '<span class="badge bg-amber-100 text-amber-800 border-0">🆕 missing(候補)</span>'
    )

    # サイドバー active 判定
    nav_active = {
        "project": "projects",
        "per_project": "settings",
        "per_item": "items",
        "global_utility": "admin",
        "error": "",
        "global": "dashboard" if "dashboard" in sid else "account" if "account" in sid else "",
    }.get(scope, "")

    def sidebar_link(href: str, label: str, key: str) -> str:
        active = "bg-white/12 text-white font-medium" if key == nav_active else "text-white/75 hover:bg-white/8 hover:text-white"
        return f'<a href="{href}" class="block px-4 py-2 rounded-lg text-sm {active}">{label}</a>'

    sidebar_html = "\n".join([
        sidebar_link("dashboard-kpi.html", "ダッシュボード", "dashboard"),
        sidebar_link("projects-list.html", "プロジェクト", "projects"),
        sidebar_link("project-detail.html", "アイテム一覧", "items"),
        sidebar_link("settings-general.html", "設定", "settings"),
        sidebar_link("asset-library.html", "管理", "admin"),
    ])

    # edges を リンクボタンに
    edges_buttons = []
    for edge in screen.get("edges", []) or []:
        to_id = edge.get("to")
        if to_id not in all_screens:
            continue
        to_screen = all_screens[to_id]
        to_label = to_screen.get("name", to_id)
        to_status = to_screen.get("status", "designed")
        to_scope = to_screen.get("scope", "global")
        edge_style = edge.get("style", "solid")
        # 採用 = 通常ボタン、 抜け = outline 点線風
        if edge_style == "dashed" or to_status != "designed":
            btn_cls = "btn btn-sm btn-outline border-dashed text-gray-600"
        else:
            btn_cls = "btn btn-sm bg-slate-800 hover:bg-slate-700 text-white border-0"
        edges_buttons.append(
            f'<a href="{to_id}.html" class="{btn_cls}">→ {to_label} '
            f'<span class="text-xs opacity-60 ml-1">[{SCOPE_META[to_scope]["icon"]}]</span></a>'
        )
    edges_html = "\n".join(edges_buttons) if edges_buttons else '<span class="text-sm text-gray-400">(他画面への遷移なし)</span>'

    # 反対方向: この画面 を 指している edges(incoming)
    incoming_buttons = []
    for other_id, other_screen in all_screens.items():
        for edge in other_screen.get("edges", []) or []:
            if edge.get("to") == sid:
                other_name = other_screen.get("name", other_id)
                other_scope = other_screen.get("scope", "global")
                incoming_buttons.append(
                    f'<a href="{other_id}.html" class="btn btn-sm btn-ghost text-gray-600">'
                    f'← {other_name} <span class="text-xs opacity-60 ml-1">[{SCOPE_META[other_scope]["icon"]}]</span></a>'
                )
    incoming_html = "\n".join(incoming_buttons) if incoming_buttons else '<span class="text-sm text-gray-400">(なし)</span>'

    # 画像
    if image_url:
        image_html = f'<img src="{image_url}" alt="{name}" class="w-full max-w-5xl mx-auto rounded-lg shadow-sm border border-gray-200">'
    else:
        image_html = (
            '<div class="w-full max-w-5xl mx-auto aspect-video rounded-lg border-2 border-dashed border-gray-300 bg-gray-50 flex items-center justify-center">'
            '<div class="text-center"><div class="text-7xl text-gray-300 mb-3">?</div>'
            '<div class="text-gray-500">画像未生成(missing 候補)</div></div></div>'
        )

    return f'''<!doctype html>
<html lang="ja" data-theme="light">
<head>
<meta charset="utf-8">
<title>{name} / Example Studio</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdn.jsdelivr.net/npm/daisyui@4/dist/full.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  html, body {{ font-family: 'Noto Sans JP', sans-serif; background: #fafafa; }}
  .sidebar {{ background: #1B3A5C; }}
</style>
</head>
<body class="min-h-screen flex">

<aside class="sidebar w-56 flex-shrink-0 text-white flex flex-col">
  <div class="px-5 py-5 border-b border-white/10">
    <div class="font-bold text-lg">Example Studio</div>
    <div class="text-xs text-white/50 mt-0.5">サンプル制作ツール</div>
  </div>
  <nav class="p-3 flex-1 space-y-0.5">
    {sidebar_html}
  </nav>
  <div class="p-3 border-t border-white/10 text-xs text-white/60">
    <div>v1 mock</div>
    <div class="mt-1"><a href="index.html" class="underline">sitemap</a></div>
  </div>
</aside>

<div class="flex-1 flex flex-col min-w-0">
  <header class="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between gap-3">
    <div class="flex items-center gap-2 text-sm">
      <a href="index.html" class="text-gray-600 hover:text-slate-800">sitemap</a>
      <span class="text-gray-400">/</span>
      <span class="text-gray-600">{scope_meta["icon"]} {scope_meta["label"]}</span>
      <span class="text-gray-400">/</span>
      <span class="font-medium text-slate-800">{name}</span>
    </div>
    <div class="flex items-center gap-2">
      {status_badge}
      <span class="badge badge-outline text-xs">{sid}</span>
    </div>
  </header>

  <main class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-7xl mx-auto">
      <!-- mockup 画像 -->
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
        {image_html}
      </div>

      <!-- 遷移先(outgoing edges) -->
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5 mb-4">
        <h3 class="text-sm font-bold text-slate-700 uppercase mb-3">→ この画面からの遷移</h3>
        <div class="flex flex-wrap gap-2">
          {edges_html}
        </div>
      </div>

      <!-- 流入(incoming edges) -->
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <h3 class="text-sm font-bold text-slate-700 uppercase mb-3">← この画面への流入</h3>
        <div class="flex flex-wrap gap-2">
          {incoming_html}
        </div>
      </div>
    </div>
  </main>

  <footer class="bg-white border-t border-gray-200 px-6 py-2 text-xs text-gray-500 text-center">
    Web モック / build_html_mockups.py で 自動生成 / screens.yaml v1
  </footer>
</div>

</body>
</html>
'''


def build_index_html(screens: list[dict]) -> str:
    """sitemap index: 全画面 を grid 表示、 各画面へ クリック遷移。"""
    by_scope: dict[str, list[dict]] = {}
    for s in screens:
        by_scope.setdefault(s["scope"], []).append(s)

    n_designed = sum(1 for s in screens if s.get("status") == "designed")
    n_missing = len(screens) - n_designed
    sections = []
    for scope_name in ["global", "project", "per_project", "per_item", "global_utility", "error"]:
        if scope_name not in by_scope:
            continue
        meta = SCOPE_META[scope_name]
        cards = []
        for s in by_scope[scope_name]:
            sid = s["id"]
            name = s.get("name", "(no name)")
            status = s.get("status", "designed")
            status_icon = "✅" if status == "designed" else "🆕"
            cards.append(
                f'<a href="{sid}.html" class="block bg-white rounded-xl shadow-sm border border-gray-100 p-4 hover:shadow-md hover:border-slate-300 transition">'
                f'<div class="text-xs text-gray-400 mb-1">{status_icon} {sid}</div>'
                f'<div class="font-semibold text-slate-800">{name}</div>'
                f'</a>'
            )
        sections.append(
            f'<section class="mb-8">'
            f'<h2 class="text-lg font-bold text-slate-700 mb-3">{meta["icon"]} {meta["label"]}'
            f'<span class="text-sm text-gray-400 ml-2 font-normal">({len(by_scope[scope_name])} 画面)</span></h2>'
            f'<div class="grid grid-cols-4 gap-3">{"".join(cards)}</div>'
            f'</section>'
        )

    return f'''<!doctype html>
<html lang="ja" data-theme="light">
<head>
<meta charset="utf-8">
<title>サンプルWebUI Web モック sitemap</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdn.jsdelivr.net/npm/daisyui@4/dist/full.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  html, body {{ font-family: 'Noto Sans JP', sans-serif; background: #fafafa; }}
</style>
</head>
<body class="min-h-screen">

<header class="bg-slate-800 text-white px-8 py-5">
  <h1 class="text-xl font-bold">サンプルWebUI Web モック</h1>
  <p class="text-sm text-white/70 mt-1">{len(screens)} 画面(設計済 {n_designed} + 抜け候補 {n_missing})/ 各カードクリックで個別画面へ</p>
</header>

<main class="p-8 max-w-7xl mx-auto">
{"".join(sections)}
</main>

<footer class="px-8 py-4 text-center text-xs text-gray-500 bg-white border-t">
  Mermaid sitemap: <a href="../sitemap.png" class="text-blue-600 underline">sitemap.png</a>
  &nbsp;|&nbsp; <a href="../sitemap.md" class="text-blue-600 underline">sitemap.md</a>
</footer>

</body>
</html>
'''


def resolve_image_url(screen: dict) -> str | None:
    """画面の画像 URL を 解決。 採用 = accepted_screens/、 missing = missing_screens/<id>.png"""
    if screen.get("status") == "designed" and screen.get("image"):
        # screens.yaml の image フィールドは accepted_screens/ 相対
        return f"../{screen['image']}"
    else:
        # missing は missing_screens/<id>.png(架空 ID から ファイル名 推測)
        sid = screen["id"]
        # screens.yaml の id (kebab-case)を missing_screens のファイル名(G1_dashboard_kpi 等)に マッピング
        id_to_filename = {  # example mapping (synthetic)
            "dashboard-kpi": "G1_dashboard_kpi",
            "account-settings": "G2_account_settings",
            "asset-library": "U1_asset_library",
            "login": "E1_login",
        }
        fname = id_to_filename.get(sid)
        if fname:
            return f"../missing_screens/{fname}.png"
        return None


def main() -> int:
    sb = yaml.safe_load(SCREENS_YAML.read_text(encoding="utf-8"))
    screens = sb["screens"]
    all_screens = {s["id"]: s for s in screens}
    CLICKABLE_DIR.mkdir(parents=True, exist_ok=True)

    # 既存 *.html を 一旦全削除(backup は既に取得済)
    for old in CLICKABLE_DIR.glob("*.html"):
        old.unlink()

    print(f"Building {len(screens)} HTML mockups → {CLICKABLE_DIR}")
    for screen in screens:
        sid = screen["id"]
        image_url = resolve_image_url(screen)
        html = html_template(screen, all_screens, image_url)
        out = CLICKABLE_DIR / f"{sid}.html"
        out.write_text(html, encoding="utf-8")
        status_icon = "✅" if screen.get("status") == "designed" else "🆕"
        print(f"  {status_icon} {sid}.html")

    # index.html(sitemap 起点)
    index_html = build_index_html(screens)
    (CLICKABLE_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"  📋 index.html (sitemap)")

    print(f"\nDone. Open: {CLICKABLE_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
