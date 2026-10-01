#!/usr/bin/env python3
"""screens.yaml を `window.SCREENS_DATA = {...}` 形式の static JS に変換。

file:// プロトコルでは fetch() がブロックされるため、 JSON ファイルを 別途
読む方式は 使えない。 代わりに `<script src="screens-data.js">` で window
global に bind して shell.js から 同期的に読む。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    print("PyYAML が必要")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent
CLICKABLE_DIR = ROOT / "mockups" / "clickable"
SCREENS_YAML = ROOT / "mockups" / "screens.yaml"
OUT = CLICKABLE_DIR / "screens-data.js"


def main() -> int:
    data = yaml.safe_load(SCREENS_YAML.read_text(encoding="utf-8"))
    # JS で扱いやすい形に整形 (id 引きやすいよう by_id map も同梱)
    out = {
        "schema_version": data.get("schema_version"),
        "scope_sub_nav": data.get("scope_sub_nav", {}),
        "screens": data["screens"],
    }
    js = (
        "// auto-generated from screens.yaml — DO NOT EDIT BY HAND\n"
        "window.SCREENS_DATA = "
        + json.dumps(out, ensure_ascii=False, indent=2)
        + ";\n"
    )
    OUT.write_text(js, encoding="utf-8")
    print(f"Wrote {OUT} ({len(out['screens'])} screens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
