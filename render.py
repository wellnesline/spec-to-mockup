#!/usr/bin/env python3
"""sitemap render: screens.yaml → sitemap.excalidraw を 1 関数で出力。
   layout + render を 統合(scope-aware 座標 + 画像埋込 + 矢印描画 + 衝突回避)。
   既存 (既存の sitemap 生成スクリプト) の 270 行 を 流用 + screens.yaml 入力対応。

   責務(SITEMAP-LINT-011 対応):
     - scope-aware 座標: 6 scope ごとに 矩形領域を hard code、 scope 内では hint_row x hint_col で 決定的配置
     - 衝突回避: scope 矩形が重ならない(hard code)、 scope 内では hint 重複を 呼び出し側責任
     - 矢印交差最小化: best-effort のみ、 完全最適化は NP-hard のため放棄、 人間目視で許容判定

   使い方:
     python render.py <screens_yaml> <output_excalidraw> [--mockup-dir PATH]
"""
from __future__ import annotations
import argparse
import base64
import json
import secrets
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

ROOT = Path(__file__).resolve().parent
DEFAULT_MOCKUP_DIR = ROOT / "mockups"

NOW = int(time.time() * 1000)


# ─── Scope レイアウト hard code(衝突回避: 矩形重ならない)──────────────
SCOPE_LAYOUT = {
    "global": {
        "x": 40, "y": 30, "w": 560, "h": 250,
        "label": "global scope",
        "color": "#6366f1", "bg": "#eef2ff",
    },
    "project": {
        "x": 620, "y": 80, "w": 1180, "h": 470,
        "label": "project scope (project context あり)",
        "color": "#10b981", "bg": "#ecfdf5",
    },
    "per_project": {
        "x": 620, "y": 580, "w": 740, "h": 740,
        "label": "🔒 per-project scope (設定タブ、 project ごとに独立)",
        "color": "#d97706", "bg": "#fffbeb",
    },
    "per_item": {
        "x": 1400, "y": 580, "w": 800, "h": 900,
        "label": "🟪 per-item scope (item ごとに独立)",
        "color": "#db2777", "bg": "#fdf2f8",
    },
    "global_utility": {
        "x": 40, "y": 580, "w": 560, "h": 600,
        "label": "global utility (ライブラリ / 通知 等)",
        "color": "#6366f1", "bg": "#eef2ff",
    },
    "error": {
        "x": 40, "y": 1210, "w": 560, "h": 240,
        "label": "global error / auth",
        "color": "#6366f1", "bg": "#eef2ff",
    },
}

NODE_W, NODE_H = 280, 195
LABEL_H = 90  # node 下のラベル領域
COL_PITCH = 300
ROW_PITCH = NODE_H + LABEL_H + 30  # 315


# ─── Excalidraw element builders(既存 gen script から流用)────────────
def nid() -> str:
    return secrets.token_urlsafe(15)


def base_props() -> dict:
    return {
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": secrets.randbelow(2_000_000_000),
        "version": 1,
        "versionNonce": secrets.randbelow(2_000_000_000),
        "isDeleted": False,
        "boundElements": [],
        "updated": NOW,
        "link": None,
        "locked": False,
        "index": None,
    }


def rect(x, y, w, h, *, stroke="#1e1e1e", bg="transparent", dashed=False) -> dict:
    return base_props() | {
        "id": nid(),
        "type": "rectangle",
        "x": x, "y": y, "width": w, "height": h,
        "strokeColor": stroke,
        "backgroundColor": bg,
        "strokeStyle": "dashed" if dashed else "solid",
        "roundness": {"type": 3},
    }


def text(x, y, content, *, font_size=16, color="#1e1e1e", bold=False, width=None) -> dict:
    w = width if width else max(80, len(content) * (font_size * 0.7))
    h = font_size + 8
    return base_props() | {
        "id": nid(),
        "type": "text",
        "x": x, "y": y, "width": w, "height": h,
        "strokeColor": color,
        "fontSize": font_size,
        "fontFamily": 5,
        "textAlign": "left",
        "verticalAlign": "top",
        "baseline": int(font_size * 0.75),
        "containerId": None,
        "originalText": content,
        "text": content,
        "autoResize": True,
        "lineHeight": 1.25,
    }


def image_elem(x, y, w, h, file_id) -> dict:
    return base_props() | {
        "id": nid(),
        "type": "image",
        "x": x, "y": y, "width": w, "height": h,
        "fileId": file_id,
        "scale": [1, 1],
        "status": "saved",
        "crop": None,
    }


def arrow(x1, y1, x2, y2, *, dashed=False, stroke="#475569",
          start_id: str | None = None, end_id: str | None = None,
          elbowed: bool = True) -> dict:
    """矢印を生成。 start_id/end_id を 指定すると excalidraw 側で ノードに binding
    される(elbowed=True で 90度ターン path 自動生成 = ノード矩形を 自動回避)。"""
    dx = x2 - x1
    dy = y2 - y1
    return base_props() | {
        "id": nid(),
        "type": "arrow",
        "x": x1, "y": y1,
        "width": abs(dx), "height": abs(dy),
        "strokeColor": stroke,
        "strokeWidth": 2,
        "strokeStyle": "dashed" if dashed else "solid",
        "points": [[0, 0], [dx, dy]],
        "lastCommittedPoint": None,
        "startBinding": {"elementId": start_id, "focus": 0, "gap": 8, "fixedPoint": None} if start_id else None,
        "endBinding": {"elementId": end_id, "focus": 0, "gap": 8, "fixedPoint": None} if end_id else None,
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "elbowed": elbowed,
    }


def get_edge_endpoints(
    from_x: float, from_y: float, from_w: float, from_h: float,
    to_x: float, to_y: float, to_w: float, to_h: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """from ノード(矩形)から to ノード(矩形)への矢印の 始点/終点 を
    ノード境界の中点(上下左右どれか)に算出。 縦/横どちらかの 方向優位で 決定。
    これで「縁から出る」 を実現(中心通過しない)。"""
    fx_c, fy_c = from_x + from_w / 2, from_y + from_h / 2
    tx_c, ty_c = to_x + to_w / 2, to_y + to_h / 2

    dx = tx_c - fx_c
    dy = ty_c - fy_c

    if abs(dy) >= abs(dx):
        # 縦方向優位
        if dy > 0:  # to が下
            start = (fx_c, from_y + from_h)
            end = (tx_c, to_y)
        else:  # to が上
            start = (fx_c, from_y)
            end = (tx_c, to_y + to_h)
    else:
        # 横方向優位
        if dx > 0:  # to が右
            start = (from_x + from_w, fy_c)
            end = (to_x, ty_c)
        else:  # to が左
            start = (from_x, fy_c)
            end = (to_x + to_w, ty_c)
    return start, end


def load_image_file(path: Path) -> tuple[str, dict]:
    file_id = nid()
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode()
    return file_id, {
        "id": file_id,
        "mimeType": "image/png",
        "dataURL": f"data:image/png;base64,{b64}",
        "created": NOW,
        "lastRetrieved": NOW,
    }


# ─── Main render ───────────────────────────────────────────────
def render(screens_yaml: Path, output: Path, mockup_dir: Path) -> dict:
    """screens.yaml を読み込み sitemap.excalidraw を出力。 stats 返却."""
    sb = yaml.safe_load(screens_yaml.read_text(encoding="utf-8"))
    screens = sb["screens"]

    elements: list[dict] = []
    files: dict[str, dict] = {}
    screen_center: dict[str, tuple[float, float]] = {}
    screen_to_node_id: dict[str, str] = {}  # 矢印 binding 用: screen.id → node 要素の id
    screen_to_rect: dict[str, tuple[float, float, float, float]] = {}  # 端点計算用: screen.id → (x, y, w, h)

    # 1. Scope 背景矩形 + ラベル
    for scope_name, layout in SCOPE_LAYOUT.items():
        e = rect(
            layout["x"], layout["y"], layout["w"], layout["h"],
            stroke=layout["color"], bg=layout["bg"], dashed=True,
        )
        elements.append(e)
        elements.append(text(
            layout["x"] + 10, layout["y"] + 8, layout["label"],
            font_size=14, color=layout["color"], bold=True,
        ))

    # 2. Screens を 配置(scope 内 hint_row x hint_col)
    for screen in screens:
        scope = screen["scope"]
        if scope not in SCOPE_LAYOUT:
            print(f"  WARN: unknown scope '{scope}' for screen {screen['id']}", file=sys.stderr)
            continue
        layout = SCOPE_LAYOUT[scope]
        pos = screen.get("position", {})
        row = pos.get("hint_row", 0)
        col = pos.get("hint_col", 0)

        x = layout["x"] + 30 + col * COL_PITCH
        y = layout["y"] + 40 + row * ROW_PITCH

        # node 矩形 or 画像(矢印 binding のため id を 保存)
        node_elem: dict
        if screen.get("status") == "designed" and screen.get("image"):
            img_path = mockup_dir / screen["image"]
            if img_path.exists():
                fid, fobj = load_image_file(img_path)
                files[fid] = fobj
                node_elem = image_elem(x, y, NODE_W, NODE_H, fid)
            else:
                # 画像欠落 = dashed 矩形で代用
                node_elem = rect(x, y, NODE_W, NODE_H, stroke="#94a3b8", bg="#fff", dashed=True)
        else:
            # missing = dashed 矩形 + ? マーク
            node_elem = rect(x, y, NODE_W, NODE_H, stroke="#94a3b8", bg="#f8fafc", dashed=True)

        elements.append(node_elem)
        screen_to_node_id[screen["id"]] = node_elem["id"]

        # ? マーク(missing or 画像欠落のとき)
        if node_elem["type"] == "rectangle":
            elements.append(text(x + 120, y + 70, "?", font_size=64, color="#cbd5e1", bold=True))

        # ラベル(画面 id / name / scope)
        status_mark = "✅" if screen.get("status") == "designed" else "候補"
        elements.append(text(x, y + NODE_H + 5, f"[{status_mark}] {screen['id']}", font_size=11, color="#94a3b8"))
        elements.append(text(x, y + NODE_H + 23, screen.get("name", "(no name)"), font_size=15, color="#1e293b", bold=True, width=NODE_W))

        # center + 矩形(矢印端点計算用)
        screen_center[screen["id"]] = (x + NODE_W / 2, y + NODE_H / 2)
        screen_to_rect[screen["id"]] = (x, y, NODE_W, NODE_H)

    # 3. Edges(矢印 + binding)
    # binding を 効かせるには ノード側にも boundElements を 追加する必要がある
    node_id_to_elem = {n["id"]: n for n in elements if n.get("type") in ("image", "rectangle")}
    for screen in screens:
        from_id = screen["id"]
        if from_id not in screen_to_rect or from_id not in screen_to_node_id:
            continue
        start_node_id = screen_to_node_id[from_id]
        fx, fy, fw, fh = screen_to_rect[from_id]
        for edge in screen.get("edges", []) or []:
            to_id = edge.get("to")
            if to_id not in screen_to_rect or to_id not in screen_to_node_id:
                continue
            end_node_id = screen_to_node_id[to_id]
            tx, ty, tw, th = screen_to_rect[to_id]
            # ノード境界端点(縁の中点)を算出
            (x1, y1), (x2, y2) = get_edge_endpoints(fx, fy, fw, fh, tx, ty, tw, th)
            dashed = edge.get("style") == "dashed"
            arrow_elem = arrow(
                x1, y1, x2, y2, dashed=dashed,
                start_id=start_node_id, end_id=end_node_id,
                elbowed=True,  # 90度ターン path で ノード矩形を自動回避
            )
            elements.append(arrow_elem)

            # 双方向参照: ノード側にも boundElements 追加
            for node_id in (start_node_id, end_node_id):
                if node_id in node_id_to_elem:
                    nelem = node_id_to_elem[node_id]
                    if "boundElements" not in nelem or nelem["boundElements"] is None:
                        nelem["boundElements"] = []
                    nelem["boundElements"].append({"id": arrow_elem["id"], "type": "arrow"})

    # 4. Title
    title_text = "サンプルWebUI 画面遷移図(sitemap pipeline 自動生成)"
    elements.insert(0, text(40, -50, title_text, font_size=28, color="#1B3A5C", bold=True, width=900))
    elements.insert(1, text(40, -15, f"spec v1.1 ベース / screens.yaml = {screens_yaml.name} / 全 {len(screens)} 画面",
                            font_size=13, color="#64748b", width=1000))

    # 5. Save
    doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "sitemap_pipeline_render_v1",
        "elements": elements,
        "appState": {
            "viewBackgroundColor": "#fafafa",
            "currentItemFontFamily": 5,
            "gridSize": 20,
        },
        "files": files,
    }
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = {
        "elements_count": len(elements),
        "files_count": len(files),
        "screens_total": len(screens),
        "screens_designed": sum(1 for s in screens if s.get("status") == "designed"),
        "screens_missing": sum(1 for s in screens if s.get("status") == "missing"),
        "edges_total": sum(len(s.get("edges") or []) for s in screens),
        "output_bytes": output.stat().st_size,
    }
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="screens.yaml → sitemap.excalidraw")
    ap.add_argument("screens_yaml", type=Path, help="入力 screens.yaml")
    ap.add_argument("output", type=Path, help="出力 sitemap.excalidraw")
    ap.add_argument("--mockup-dir", type=Path, default=DEFAULT_MOCKUP_DIR,
                    help=f"画像参照のベースディレクトリ (default: {DEFAULT_MOCKUP_DIR})")
    args = ap.parse_args(argv)

    if not args.screens_yaml.exists():
        print(f"ERROR: {args.screens_yaml} not found", file=sys.stderr)
        return 1

    stats = render(args.screens_yaml, args.output, args.mockup_dir)
    print(f"Saved: {args.output}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
