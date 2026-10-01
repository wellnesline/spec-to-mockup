#!/usr/bin/env python3
"""全 HTML mock の 視覚レイアウト整合性チェック (ヘッドレスChromium)。

regex audit (`check_html_full.py`) が 「DOM 文字列の整合性」 までしか
見ないため、 実際に CSS が効いた状態でのレンダリング崩れを 拾えない。
本スクリプトは Playwright で各画面を開き、

  L1 sidebar 位置 (`aside.sidebar` が左 0 / 幅 180+)
  L2 sub-nav 位置 (`.scope-sub-nav` が main より上 / 幅 600+)
  L3 横スクロール (body.scrollWidth <= viewport.width + 8)
  L4 stylesheet 読み込み (Tailwind + daisyUI CDN 応答 200)
  L5 スクショ取得 (失敗画面のみ mockups/clickable/_visual_audit_screens/ に保存)

を 検査し _visual_audit.md に レポートする。

failure 数 > 0 で exit 1。
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from collections import defaultdict

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    import yaml  # type: ignore
except ImportError:
    print("PyYAML が必要")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent
CLICKABLE_DIR = ROOT / "mockups" / "clickable"
SCREENS_YAML = ROOT / "mockups" / "screens.yaml"
SCREENSHOT_DIR = CLICKABLE_DIR / "_visual_audit_screens"
REPORT = CLICKABLE_DIR / "_visual_audit.md"

VIEWPORT = {"width": 1440, "height": 900}
NAV_TIMEOUT = 10_000
NETWORK_IDLE_TIMEOUT = 5_000

EXPECTED_CDN_HOSTS = {
    "cdn.tailwindcss.com": "Tailwind",
    "cdn.jsdelivr.net": "daisyUI",
}


def load_screens() -> tuple[list[dict], dict]:
    data = yaml.safe_load(SCREENS_YAML.read_text(encoding="utf-8"))
    return data["screens"], data.get("scope_sub_nav", {})


def check_one(page, html_path: Path, screen: dict, scope_sub_nav: dict) -> dict:
    """1 画面の視覚チェック結果 を dict で返す."""
    result: dict = {
        "screen": html_path.stem,
        "scope": screen.get("scope"),
        "failures": [],
        "warnings": [],
    }

    # network 応答 収集 (L4 用)
    cdn_responses: dict[str, int] = {}

    def on_response(resp):
        for host in EXPECTED_CDN_HOSTS:
            if host in resp.url:
                cdn_responses[host] = resp.status

    page.on("response", on_response)

    try:
        page.goto(html_path.as_uri(), timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except PWTimeout:
            pass  # idle 不達はOK (CDN 遅延などで)
        # shell.js が DOM 注入する時間を 確保 (defer + DOMContentLoaded で 即注入されるが
        # 念のため小さく待つ)
        page.wait_for_timeout(150)
    except PWTimeout as e:
        result["failures"].append(f"navigation timeout: {e}")
        return result

    # L4 stylesheet
    for host, label in EXPECTED_CDN_HOSTS.items():
        status = cdn_responses.get(host)
        if status is None:
            result["failures"].append(f"L4 {label} CDN 応答 なし ({host})")
        elif status != 200:
            result["failures"].append(f"L4 {label} CDN status={status} ({host})")

    # L1 sidebar 位置
    # - login / error: 認証/エラー画面なので sidebar 不要 (built-in 許容)
    # - chrome_layout == "modal_fullscreen": ウィザード等フルスクリーン modal、
    #   wizard-header 等を 使う前提で sidebar/topbar/sub-nav 不要
    sid = screen["id"]
    chrome_layout = screen.get("chrome_layout", "standard")
    skip_sidebar = sid in ("login", "error-page") or chrome_layout == "modal_fullscreen"
    if not skip_sidebar:
        sidebar_info = page.evaluate(
            """() => {
                const el = document.querySelector('aside.sidebar, aside[class*="sidebar"]');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const cs = getComputedStyle(el);
                // 背景色 RGB を分解
                const bg = cs.backgroundColor; // "rgb(r,g,b)" or "rgba(...,a)"
                const m = bg.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
                const rgba = m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3]), m[4]==null?1:parseFloat(m[4])] : null;
                // 最初の nav リンクの文字色 (コントラスト確認用)
                const link = el.querySelector('nav a');
                const linkColor = link ? getComputedStyle(link).color : null;
                return {left: r.left, width: r.width, height: r.height,
                        visible: r.width > 0 && r.height > 0,
                        bg, rgba, linkColor};
            }"""
        )
        if not sidebar_info:
            result["failures"].append("L1 sidebar 要素 なし")
        elif not sidebar_info["visible"]:
            result["failures"].append("L1 sidebar 不可視 (width/height=0)")
        elif sidebar_info["left"] > 8:
            result["failures"].append(
                f"L1 sidebar 左端 != 0 (left={sidebar_info['left']:.0f}px)"
            )
        elif sidebar_info["width"] < 180:
            result["failures"].append(
                f"L1 sidebar 幅 < 180 (width={sidebar_info['width']:.0f}px)"
            )
        else:
            # L1.5 visibility: background が 透明 / 白に近い と sidebar が見えない
            rgba = sidebar_info["rgba"]
            if rgba is None:
                result["failures"].append(f"L1.5 sidebar bg parse 失敗: {sidebar_info['bg']}")
            else:
                r_, g_, b_, a_ = rgba
                if a_ < 0.5:
                    result["failures"].append(
                        f"L1.5 sidebar bg alpha < 0.5 (透明、 文字色と被って消失): rgba={rgba}"
                    )
                else:
                    # sidebar 内の text 色 (白系想定) との luminance 差で コントラスト確認
                    # 簡易: bg luminance < 0.5 (= 暗色) であること を期待 (text-white 前提)
                    lum = (0.299 * r_ + 0.587 * g_ + 0.114 * b_) / 255.0
                    if lum > 0.7:
                        result["failures"].append(
                            f"L1.5 sidebar bg が明色 (luminance={lum:.2f}) で white text と コントラスト不足: rgba={rgba}"
                        )

    # L2 sub-nav (scope に sub-nav が定義されてる画面のみ。
    # modal_fullscreen は sub-nav 不要なので skip)
    if screen.get("scope") in scope_sub_nav and chrome_layout != "modal_fullscreen":
        sub_nav_rect = page.evaluate(
            """() => {
                const el = document.querySelector('.scope-sub-nav');
                const main = document.querySelector('main');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const mr = main ? main.getBoundingClientRect() : null;
                return {
                    top: r.top, left: r.left, width: r.width, height: r.height,
                    main_top: mr ? mr.top : null,
                    link_count: el.querySelectorAll('a').length,
                };
            }"""
        )
        if not sub_nav_rect:
            result["failures"].append("L2 scope-sub-nav 要素 なし")
        else:
            if sub_nav_rect["width"] < 400:
                result["failures"].append(
                    f"L2 sub-nav 幅 < 400 (width={sub_nav_rect['width']:.0f}px) — 縦並びの可能性"
                )
            if sub_nav_rect["main_top"] is not None and sub_nav_rect["top"] >= sub_nav_rect["main_top"]:
                result["failures"].append(
                    f"L2 sub-nav が main より下 (sub_top={sub_nav_rect['top']:.0f} >= main_top={sub_nav_rect['main_top']:.0f})"
                )
            expected_link_count = len(scope_sub_nav[screen["scope"]]["items"])
            if sub_nav_rect["link_count"] != expected_link_count:
                result["failures"].append(
                    f"L2 sub-nav リンク数 {sub_nav_rect['link_count']} != 期待 {expected_link_count}"
                )

    # L3 横スクロール
    overflow = page.evaluate(
        """() => ({sw: document.body.scrollWidth, vw: window.innerWidth})"""
    )
    if overflow["sw"] > overflow["vw"] + 8:
        result["failures"].append(
            f"L3 横スクロール発生 (body.scrollWidth={overflow['sw']} > viewport={overflow['vw']})"
        )

    # L5 スクショ (失敗時のみ)
    if result["failures"]:
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        shot_path = SCREENSHOT_DIR / f"{sid}.png"
        try:
            page.screenshot(path=str(shot_path), full_page=True)
            result["screenshot"] = str(shot_path.relative_to(CLICKABLE_DIR))
        except Exception as e:
            result["warnings"].append(f"screenshot 失敗: {e}")

    return result


def main() -> int:
    screens, scope_sub_nav = load_screens()
    print(f"Visual audit: {len(screens)} screens, viewport={VIEWPORT}")
    print()

    results: list[dict] = []
    failures_by_screen: dict[str, list[str]] = defaultdict(list)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()

        for s in screens:
            html_path = CLICKABLE_DIR / f"{s['id']}.html"
            if not html_path.exists():
                results.append({"screen": s["id"], "failures": ["HTML file missing"], "warnings": []})
                continue
            r = check_one(page, html_path, s, scope_sub_nav)
            results.append(r)
            marker = "✅" if not r["failures"] else "❌"
            extra = ""
            if r["failures"]:
                extra = " | " + "; ".join(r["failures"])
            print(f"  {marker} {r['screen']:30s}{extra}")
            if r["failures"]:
                failures_by_screen[r["screen"]] = r["failures"]

        browser.close()

    # レポート
    total_failures = sum(len(r["failures"]) for r in results)
    pass_count = sum(1 for r in results if not r["failures"])
    report = ["# HTML Mock 視覚レイアウト Audit (Playwright)", ""]
    report.append("## サマリ")
    report.append(f"- 検査: {len(results)} 画面 / viewport={VIEWPORT}")
    report.append(f"- PASS: {pass_count}")
    report.append(f"- FAIL: {len(results) - pass_count}")
    report.append(f"- 失敗合計: {total_failures} 件")
    report.append("")

    if failures_by_screen:
        report.append("## ❌ 失敗詳細")
        for sid, fails in failures_by_screen.items():
            report.append(f"### `{sid}`")
            for f in fails:
                report.append(f"- {f}")
            r = next((x for x in results if x["screen"] == sid), {})
            if r.get("screenshot"):
                report.append(f"- スクショ: `{r['screenshot']}`")
            report.append("")
    else:
        report.append("## ✅ 全画面 PASS")
        report.append("")

    # JSON 詳細
    json_path = CLICKABLE_DIR / "_visual_audit.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT.write_text("\n".join(report), encoding="utf-8")

    print()
    print(f"Report: {REPORT}")
    print(f"JSON:   {json_path}")
    print(f"Result: PASS={pass_count} FAIL={len(results) - pass_count} (失敗合計 {total_failures})")
    return 1 if total_failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
