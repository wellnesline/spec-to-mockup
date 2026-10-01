#!/usr/bin/env python3
"""sitemap_pipeline 全工程を 1 コマンドで実行 (shell.js 共通化版)。

工程:
   1. build_screens_data.py    (screens.yaml → screens-data.js / window.SCREENS_DATA)
   2. refactor_to_shell.py     (各 HTML を 本体のみ + shell.js include に reduce)
   3. check_html_full.py       (静的 audit: shell 構成 / dead link / orphan)
   4. check_html_visual.py     (ヘッドレス Chromium: L1-L5 視覚 audit)

   いずれかで exit != 0 なら 全体を 失敗扱い。

   chrome (sidebar / breadcrumb / scope-sub-nav) は shell.js が runtime で
   全画面に 同一ソースから 動的注入するため、 patcher (旧 3 本) は archive/ へ。
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    ("build_screens_data.py", "screens-data.js 生成"),
    ("refactor_to_shell.py", "HTML を shell 構成に refactor"),
    ("check_html_full.py", "静的 audit"),
    ("check_html_visual.py", "視覚 audit (Playwright)"),
]


def main() -> int:
    fails: list[str] = []
    for script, label in STEPS:
        path = ROOT / script
        if not path.exists():
            print(f"⏭  {label}: {script} 不在")
            continue
        print(f"\n=== {label} ({script}) ===")
        r = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            fails.append(f"{script} (exit={r.returncode})")

    print("\n" + "=" * 60)
    if fails:
        print("❌ 失敗:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("✅ 全工程 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
