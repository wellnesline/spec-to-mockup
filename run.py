#!/usr/bin/env python3
"""sitemap pipeline orchestrator(サンプルWebUI 半自律パイプライン v1)

   フロー:
     G0 (人間ゲート) → architect → render → reviewer → G3 (人間ゲート pause)
       OK  → 確定
       NG  → human_issue.md 記述 → architect 再走(prev_screens + review + issue 入力必須)→ render → reviewer → G3
       最大 1 revise

   本 orchestrator は LLM agent spawn を **行わない**(Claude Code が呼び出して 自分で agent spawn する想定)。
   この script は:
     - state.json で iter / revise_round を管理
     - render.py を サブプロセスで起動
     - 各 stage の前提ファイル整合性を機械検証(SITEMAP-LINT 9+4 件)
     - G0 / G3 で pause(stdout に手順を表示し exit 0)
     - 人間が手動で「次へ」 と言ったら 再起動

   使い方:
     # Stage 0: G0 認識合わせ(初回)
     python run.py g0

     # Stage 1: architect 走行(Claude が agent spawn する前に呼ぶ準備)
     python run.py architect-prepare

     # Stage 2: architect が screens.yaml 書いた後、 render 実行
     python run.py render

     # Stage 3: reviewer 走行準備
     python run.py reviewer-prepare

     # Stage 4: G3 人間目視結果反映
     python run.py g3 --ok       # OK で確定
     python run.py g3 --ng       # NG = revise 1 回 開始(human_issue.md 必要)

     # 全 lint 走行
     python run.py lint

     # 状態確認
     python run.py status
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"  # design/spec documents (not included in this public copy)
MOCKUP_DIR = ROOT / "mockups"
STATE_FILE = MOCKUP_DIR / ".sitemap_pipeline_state.json"
SPEC_DOC = DOCS / "webui_spec_v1.md"
DESIGN_DOC = DOCS / "webui_sitemap_pipeline_design_v1.md"
SCREENS_YAML = MOCKUP_DIR / "screens.yaml"
SITEMAP_EXCALIDRAW = MOCKUP_DIR / "sitemap.excalidraw"
REVIEW_MD = MOCKUP_DIR / "review.md"
HUMAN_ISSUE_MD = MOCKUP_DIR / "human_issue.md"
G0_MEMO = MOCKUP_DIR / "g0_memo.md"

RENDER_PY = ROOT / "render.py"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "stage": "init",
        "revise_round": 0,
        "screens_yaml_hash": None,
        "g0_approved": False,
        "g3_verdict": None,
    }


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ─── Lint 規則(13 件、 設計書文面検査)──────────────────────────
LINT_RULES = [
    # 基本 9 件
    ("SITEMAP-LINT-001", "WARN", r"自律パイプライン(?!の言葉|表現)", "「自律」 単独表現(「半自律」推奨)"),
    ("SITEMAP-LINT-002", "BLOCK", r"(?:agent|エージェント)[^0-9]*?(\d+)\s*体", "agent カウント >4 は BLOCK", "count_check"),
    ("SITEMAP-LINT-003", "BLOCK", r"人間代理|人間\s*persona|人間[-_]?persona|qa[-_]?人間|sitemap-qa-人間", "人間代理 系語の出現"),
    ("SITEMAP-LINT-004", "BLOCK", r"重大指摘ゼロ|重大ゼロ|LLM\s*が判定|LLM\s*が.*?判定", "停止条件 LLM 判定の復活"),
    ("SITEMAP-LINT-005", "BLOCK", r"persona-qa-loop\s+skill\s+流用", "persona-qa-loop skill 流用の復活"),
    ("SITEMAP-LINT-006", "MIXED", r"最大\s*(\d+)\s*(?:iter|回)", "iter 上限 N>=3 で WARN、 N>=5 で BLOCK", "iter_check"),
    ("SITEMAP-LINT-007", "WARN", r"合計\s*\*?\*?\s*(\d+)\s*-?\s*(\d+)?\s*時間", "工数 4h 超で WARN", "hours_check"),
    ("SITEMAP-LINT-008", "BLOCK", r"\b(layouter|renderer|aggregator|revisor)\.py\b", "禁止 script ファイル名"),
    ("SITEMAP-LINT-009", "REQUIRE", r"(G0|G3|人間ゲート|目視確認)", "人間ゲート語の最低 1 件 出現"),
    # 補強 4 件
    ("SITEMAP-LINT-010", "REQUIRE", r"screens\.yaml\s+schema", "screens.yaml schema 章 が無ければ WARN"),
    ("SITEMAP-LINT-011", "REQUIRE", r"(scope-aware\s+座標|衝突回避|矢印交差最小化)", "render.py 責務記述"),
    ("SITEMAP-LINT-012", "REQUIRE", r"(網羅性.*階層.*遷移.*配置.*命名)", "reviewer 5 観点 enumerate"),
    ("SITEMAP-LINT-013", "REQUIRE", r"(再走|revise).*?(前回\s*screens\.yaml|review|reviewer\s+指摘|human_issue)", "architect 再走の入力差分要求"),
]


def lint_doc(doc_path: Path) -> list[dict]:
    """設計書を 13 lint 規則で検査。 違反リストを返す."""
    if not doc_path.exists():
        return [{"rule": "FILE", "severity": "BLOCK", "msg": f"{doc_path} not found"}]
    text = doc_path.read_text(encoding="utf-8")
    violations: list[dict] = []

    for rule_id, base_sev, pattern, desc, *check_type in LINT_RULES:
        check = check_type[0] if check_type else None
        matches = re.findall(pattern, text)

        if base_sev == "REQUIRE":
            if not matches:
                violations.append({"rule": rule_id, "severity": "BLOCK" if rule_id == "SITEMAP-LINT-009" else "WARN",
                                   "msg": f"{desc}: 該当文字列未検出"})
        elif check == "count_check":
            # agent カウント宣言を全部見て >4 を 検出
            for m in matches:
                n = int(m) if isinstance(m, str) else int(m[0])
                if n > 4:
                    violations.append({"rule": rule_id, "severity": "BLOCK",
                                       "msg": f"agent カウント宣言 {n} 体 > 4(BLOCK)"})
        elif check == "iter_check":
            for m in matches:
                n = int(m) if isinstance(m, str) else int(m[0])
                if n >= 5:
                    violations.append({"rule": rule_id, "severity": "BLOCK",
                                       "msg": f"iter 上限 N={n} >=5(BLOCK)"})
                elif n >= 3:
                    violations.append({"rule": rule_id, "severity": "WARN",
                                       "msg": f"iter 上限 N={n} >=3(WARN)"})
        elif check == "hours_check":
            for m in matches:
                lo = int(m[0]) if isinstance(m, tuple) else int(m)
                if lo > 4:
                    violations.append({"rule": rule_id, "severity": "WARN",
                                       "msg": f"工数下限 {lo}h > 4h(WARN)"})
        else:
            if matches:
                violations.append({"rule": rule_id, "severity": base_sev,
                                   "msg": f"{desc}: {len(matches)} 件検出 (例: {matches[0] if not isinstance(matches[0], tuple) else matches[0][0]!r})"})

    return violations


# ─── Stage commands ────────────────────────────────────────────
def cmd_g0() -> int:
    print("=" * 60)
    print("Stage G0: 認識合わせ(人間ゲート)")
    print("=" * 60)
    print()
    print(f"以下を確認してください:")
    print(f"  - spec doc: {SPEC_DOC}")
    print(f"  - design doc: {DESIGN_DOC}")
    print()
    print("人間判断:")
    print("  - サンプルWebUI sitemap pipeline v1 の方針で OK か")
    print("  - 6 scope(global / project / per_project / per_item / global_utility / error)で 十分か")
    print(f"  - 別の scope / 階層方針があれば {G0_MEMO} に書く")
    print()
    print("承認したら以下を実行:")
    print(f"  python run.py architect-prepare")
    print()
    state = load_state()
    state["stage"] = "g0_pending"
    save_state(state)
    return 0


def cmd_architect_prepare() -> int:
    state = load_state()
    state["g0_approved"] = True
    state["stage"] = "architect_pending"
    save_state(state)
    print("=" * 60)
    print(f"Stage Architect: screens.yaml 生成準備完了(revise round {state['revise_round']})")
    print("=" * 60)
    print()
    print("Claude Code セッションで architect agent を spawn してください:")
    print()
    if state["revise_round"] == 0:
        print(f"  Mode A (新規生成):")
        print(f"    入力 spec: {SPEC_DOC}")
        print(f"    入力 G0 メモ: {G0_MEMO} (なければ空)")
        print(f"    出力先: {SCREENS_YAML}")
    else:
        print(f"  Mode B (revise round {state['revise_round']}):")
        print(f"    入力 prev_screens: {SCREENS_YAML}")
        print(f"    入力 review: {REVIEW_MD}")
        print(f"    入力 human_issue: {HUMAN_ISSUE_MD}")
        print(f"    出力先: {SCREENS_YAML} (上書き)")
    print()
    print(f"architect 完了後:")
    print(f"  python run.py render")
    return 0


def cmd_render() -> int:
    state = load_state()
    if not SCREENS_YAML.exists():
        print(f"ERROR: {SCREENS_YAML} がありません。 architect を先に走らせてください。", file=sys.stderr)
        return 1

    # YAML schema 簡易検査
    try:
        sb = yaml.safe_load(SCREENS_YAML.read_text(encoding="utf-8"))
        assert "screens" in sb and isinstance(sb["screens"], list)
        for s in sb["screens"]:
            assert "id" in s and "name" in s and "scope" in s
    except Exception as e:
        print(f"ERROR: screens.yaml schema 違反: {e}", file=sys.stderr)
        return 1

    # diff hash 確認(revise round で 同一なら BLOCK = 空 revise 防止)
    new_hash = file_hash(SCREENS_YAML)
    if state["revise_round"] > 0 and new_hash == state.get("screens_yaml_hash"):
        print(f"ERROR: revise round {state['revise_round']} で screens.yaml に変化なし(空 revise)", file=sys.stderr)
        return 1
    state["screens_yaml_hash"] = new_hash

    # render 実行
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), str(SCREENS_YAML), str(SITEMAP_EXCALIDRAW)],
        capture_output=False,
    )
    if result.returncode != 0:
        return result.returncode

    state["stage"] = "render_done"
    save_state(state)
    print()
    print(f"次: reviewer agent を spawn してください")
    print(f"  python run.py reviewer-prepare")
    return 0


def cmd_reviewer_prepare() -> int:
    state = load_state()
    state["stage"] = "reviewer_pending"
    save_state(state)
    print("=" * 60)
    print("Stage Reviewer: 5 観点 chain QA 実行準備")
    print("=" * 60)
    print()
    print(f"Claude Code で reviewer agent を spawn してください:")
    print(f"  入力 sitemap: {SITEMAP_EXCALIDRAW}")
    print(f"  入力 screens: {SCREENS_YAML}")
    print(f"  入力 spec: {SPEC_DOC}")
    print(f"  出力先: {REVIEW_MD}")
    print()
    print("完了後 G3 人間目視へ:")
    print(f"  {SITEMAP_EXCALIDRAW} を開く  (または excalidraw.com に drag&drop)")
    print(f"  → OK なら: python run.py g3 --ok")
    print(f"  → NG なら: {HUMAN_ISSUE_MD} に issue 書いて: python run.py g3 --ng")
    return 0


def cmd_g3(verdict: str) -> int:
    state = load_state()
    state["g3_verdict"] = verdict
    save_state(state)

    if verdict == "ok":
        print("=" * 60)
        print("✅ G3 確定: sitemap.excalidraw を 採用")
        print("=" * 60)
        print(f"最終成果物: {SITEMAP_EXCALIDRAW}")
        state["stage"] = "confirmed"
        save_state(state)
        return 0
    elif verdict == "ng":
        if not HUMAN_ISSUE_MD.exists() or HUMAN_ISSUE_MD.stat().st_size < 10:
            print(f"ERROR: {HUMAN_ISSUE_MD} に 5-10 行の issue を 書いてください", file=sys.stderr)
            return 1
        if state["revise_round"] >= 1:
            print("=" * 60)
            print("⛔ G3 NG 2 回目: revise 上限到達(最大 1 回)")
            print("=" * 60)
            print("→ spec v1.1 を見直すべき。 設計の根本不整合の可能性。")
            print(f"  spec: {SPEC_DOC}")
            print(f"  design: {DESIGN_DOC}")
            return 2
        state["revise_round"] += 1
        state["stage"] = "revise_pending"
        save_state(state)
        print(f"🔁 revise round {state['revise_round']} 開始 → architect 再走")
        print(f"  python run.py architect-prepare")
        return 0
    else:
        print(f"ERROR: unknown verdict '{verdict}', expected 'ok' or 'ng'", file=sys.stderr)
        return 1


def cmd_lint() -> int:
    print("=" * 60)
    print("Lint: 設計書 + screens.yaml + agent 定義 を 13 規則で検査")
    print("=" * 60)
    # Agent definition files are not bundled in this public copy; point these at your own prompt files.
    targets = [DESIGN_DOC, ROOT / "agents" / "architect.md",
               ROOT / "agents" / "reviewer.md"]
    total_violations = 0
    for target in targets:
        print(f"\n--- {target.relative_to(ROOT)}")
        vs = lint_doc(target)
        if not vs:
            print("  ✅ all PASS")
            continue
        for v in vs:
            mark = "⛔" if v["severity"] == "BLOCK" else "⚠️"
            print(f"  {mark} {v['rule']}: {v['msg']}")
            if v["severity"] == "BLOCK":
                total_violations += 1
    print()
    print(f"BLOCK 総数: {total_violations}")
    return 1 if total_violations > 0 else 0


def cmd_status() -> int:
    state = load_state()
    print("=" * 60)
    print("Sitemap Pipeline State")
    print("=" * 60)
    for k, v in state.items():
        print(f"  {k}: {v}")
    print()
    print("Files:")
    for path in [G0_MEMO, SCREENS_YAML, SITEMAP_EXCALIDRAW, REVIEW_MD, HUMAN_ISSUE_MD]:
        exists = "✅" if path.exists() else "❌"
        print(f"  {exists} {path.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="sitemap pipeline orchestrator v1")
    ap.add_argument("command", choices=[
        "g0", "architect-prepare", "render", "reviewer-prepare", "g3", "lint", "status",
    ])
    ap.add_argument("--ok", action="store_true", help="g3 verdict OK")
    ap.add_argument("--ng", action="store_true", help="g3 verdict NG")
    args = ap.parse_args(argv)

    if args.command == "g0":
        return cmd_g0()
    elif args.command == "architect-prepare":
        return cmd_architect_prepare()
    elif args.command == "render":
        return cmd_render()
    elif args.command == "reviewer-prepare":
        return cmd_reviewer_prepare()
    elif args.command == "g3":
        if args.ok:
            return cmd_g3("ok")
        elif args.ng:
            return cmd_g3("ng")
        else:
            print("ERROR: g3 requires --ok or --ng", file=sys.stderr)
            return 1
    elif args.command == "lint":
        return cmd_lint()
    elif args.command == "status":
        return cmd_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
