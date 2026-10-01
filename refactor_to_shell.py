#!/usr/bin/env python3
"""各 HTML を 「本体コンテンツ + shell.js include」 のシンプル形式に refactor。

shell.js が runtime で sidebar / canonical-breadcrumb / scope-sub-nav を 動的注入するため、
HTML から chrome 部分 (sidebar / breadcrumb / sub-nav / outer header / topbar) を 全削除し、
本体 (<main> またはそれに準ずる block) だけ 残す。

After:
  <body data-screen-id="...">
    <div id="page-content">...本体...</div>
    <script src="screens-data.js"></script>
    <script src="shell.js" defer></script>
  </body>

modal_fullscreen / scope=error は wizard-header / ログイン画面 等で
sidebar 不要なので body 直下にそのまま (chrome 注入 skip)。
"""
from __future__ import annotations
import re
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


# chrome 削除用 regex (balanced div 削除と組合せ)
SIDEBAR_ASIDE_RE = re.compile(
    r'<aside\b[^>]*?\bclass\s*=\s*["\'][^"\']*\bsidebar\b[^"\']*["\'][^>]*>.*?</aside>',
    re.DOTALL | re.IGNORECASE,
)
CANONICAL_BC_OPEN_RE = re.compile(
    r'<div\s+class="[^"]*\bcanonical-breadcrumb\b[^"]*"[^>]*>', re.IGNORECASE
)
SCOPE_SUB_NAV_OPEN_RE = re.compile(
    r'<div\s+class="[^"]*\bscope-sub-nav\b[^"]*"[^>]*>', re.IGNORECASE
)
BREADCRUMB_BAR_OPEN_RE = re.compile(
    r'<div\s+class="breadcrumb-bar[^"]*"[^>]*>', re.IGNORECASE
)
TOPBAR_DIV_OPEN_RE = re.compile(
    r'<div\s+class="topbar[^"]*"[^>]*>', re.IGNORECASE
)
LEGACY_PAGE_HEADER_RE = re.compile(
    r'<header\s+class="bg-white\s+border-b\s+border-gray-200[^"]*"[^>]*>.*?</header>',
    re.DOTALL | re.IGNORECASE,
)
SUB_NAV_ASIDE_RE = re.compile(
    r'<aside\s+class="sub-nav[^"]*"[^>]*>.*?</aside>', re.DOTALL | re.IGNORECASE
)
TAB_BAR_RE = re.compile(
    r'<div\s+class="tab-bar[^"]*"[^>]*>.*?</div>', re.DOTALL | re.IGNORECASE
)
BODY_OPEN_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
BODY_CLOSE_RE = re.compile(r"</body>", re.IGNORECASE)
SHELL_SCRIPT_MARK_RE = re.compile(r'<script\s+src="shell\.js"', re.IGNORECASE)


_DIV_TOKEN_RE = re.compile(r"<(/?)(div)\b[^>]*>", re.IGNORECASE)


def strip_balanced_div(text: str, open_re: re.Pattern) -> str:
    """`<div ...>` の opening に対応する `</div>` を nest 考慮で balanced 削除。"""
    while True:
        m = open_re.search(text)
        if not m:
            return text
        start = m.start()
        depth = 0
        end = None
        for token in _DIV_TOKEN_RE.finditer(text, start):
            is_close = token.group(1) == "/"
            if is_close:
                depth -= 1
                if depth == 0:
                    end = token.end()
                    break
            else:
                depth += 1
        if end is None:
            return text[:start] + text[m.end():]
        text = text[:start] + text[end:]


def unwrap_outer_flex_container(text: str) -> str:
    """body 直下に <div class="flex"> や <div class="flex-1 flex flex-col"> の
    layout wrapper があれば 解除して 中身を body 直下に上げる。
    shell.js が <div class="flex"> を 新規生成して 包むので 既存は 撤去。
    """
    # body から開始
    bm = BODY_OPEN_RE.search(text)
    if not bm:
        return text
    body_start = bm.end()
    body_end_m = BODY_CLOSE_RE.search(text, pos=body_start)
    body_end = body_end_m.start() if body_end_m else len(text)
    body = text[body_start:body_end]

    # body 直下の wrapper を peel off (複数階層対応、 最大 3 階層まで)
    for _ in range(3):
        stripped = body.lstrip()
        m = re.match(
            r'<div\s+class="[^"]*\b(flex|flex-1)\b[^"]*"[^>]*>',
            stripped,
            re.IGNORECASE,
        )
        if not m:
            break
        # 対応 </div> を 探して 中身を出す
        rel_start = stripped[: m.end()]
        depth = 0
        end = None
        for token in _DIV_TOKEN_RE.finditer(stripped, m.start()):
            is_close = token.group(1) == "/"
            if is_close:
                depth -= 1
                if depth == 0:
                    end = token.end()
                    break
            else:
                depth += 1
        if end is None:
            break
        inner = stripped[m.end(): end - len("</div>")]
        body = inner

    return text[:body_start] + "\n" + body.strip() + "\n" + text[body_end:]


def refactor(text: str, screen_id: str) -> str:
    # 1. body 開きタグに data-screen-id を 注入 (既存属性は保持)
    def _body_attr(m: re.Match) -> str:
        tag = m.group(0)
        if "data-screen-id" in tag:
            return re.sub(r'data-screen-id="[^"]*"', f'data-screen-id="{screen_id}"', tag)
        return tag[:-1] + f' data-screen-id="{screen_id}">'

    text = BODY_OPEN_RE.sub(_body_attr, text, count=1)

    # 2. chrome 系を 削除
    text = SIDEBAR_ASIDE_RE.sub("", text)
    text = LEGACY_PAGE_HEADER_RE.sub("", text)
    text = SUB_NAV_ASIDE_RE.sub("", text)
    text = TAB_BAR_RE.sub("", text)
    text = strip_balanced_div(text, CANONICAL_BC_OPEN_RE)
    text = strip_balanced_div(text, SCOPE_SUB_NAV_OPEN_RE)
    text = strip_balanced_div(text, BREADCRUMB_BAR_OPEN_RE)
    text = strip_balanced_div(text, TOPBAR_DIV_OPEN_RE)

    # 3. body 直下の layout wrapper (<div class="flex">) を 解除
    text = unwrap_outer_flex_container(text)

    # 4. body 内 残ったコンテンツを <div id="page-content"> で 包む
    bm = BODY_OPEN_RE.search(text)
    body_close_m = BODY_CLOSE_RE.search(text)
    body_start = bm.end()
    body_end = body_close_m.start()
    body_inner = text[body_start:body_end]
    # 既存の <div id="page-content"> / script 行は 残す前提で 簡素化:
    # body_inner から script タグ群を 末尾に逃がし、 残りを page-content で包む
    scripts_re = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
    scripts = scripts_re.findall(body_inner)
    body_inner_no_scripts = scripts_re.sub("", body_inner).strip()

    # 既に <div id="page-content"> で 包まれていれば そのまま、 なければ 新規 wrap
    if re.search(r'<div\s+id="page-content"', body_inner_no_scripts):
        content_block = body_inner_no_scripts
    else:
        content_block = f'<div id="page-content">\n{body_inner_no_scripts}\n</div>'

    # shell.js / screens-data.js script を 必ず 末尾に 1 回ずつ
    other_scripts = [
        s for s in scripts
        if 'src="shell.js"' not in s and 'src="screens-data.js"' not in s
    ]
    new_body = (
        "\n"
        + "\n".join(other_scripts)
        + ("\n" if other_scripts else "")
        + content_block
        + "\n"
        + '<script src="screens-data.js"></script>\n'
        + '<script src="shell.js" defer></script>\n'
    )
    return text[:body_start] + new_body + text[body_end:]


def main() -> int:
    data = yaml.safe_load(SCREENS_YAML.read_text(encoding="utf-8"))
    screens_by_id = {s["id"]: s for s in data["screens"]}

    print(f"Refactoring {len(screens_by_id)} screens to shell.js form...")
    changed = 0
    for sid, screen in screens_by_id.items():
        path = CLICKABLE_DIR / f"{sid}.html"
        if not path.exists():
            print(f"  ⏭ {sid}.html: missing")
            continue
        orig = path.read_text(encoding="utf-8")
        out = refactor(orig, sid)
        if out != orig:
            path.write_text(out, encoding="utf-8")
            print(f"  ✏️ {sid}.html: refactored")
            changed += 1
        else:
            print(f"  ⏭ {sid}.html: already shell form")
    print(f"\nRefactored: {changed} / {len(screens_by_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
