"""F7 Lot 비교 기능: 수치 표(파이썬) + 규칙 기반 결론 문장(파이썬) + LLM 해석 3층 구조."""
import os
from html import escape

import config
import report
from llm_client import generate_compare_comment

CONDITION_LABELS = [
    ("temperature", "온도", "°C"),
    ("head_speed", "헤드 속도", ""),
    ("conveyor_speed", "레일 속도", ""),
]


def _get_lot_entry(lot_id: str) -> dict:
    lots = {e["lot_id"]: e for e in report.list_completed_lots()}
    if lot_id not in lots:
        raise ValueError(f"완료된 Lot이 아니거나 존재하지 않는 Lot ID입니다: {lot_id}")
    return lots[lot_id]


def _rule_based_conclusion(a: dict, b: dict) -> str:
    diff = round(a["defect_rate"] - b["defect_rate"], 2)  # a 기준 b와의 차이

    def cond_str(e):
        return f"{e['temperature']}°C, 헤드 {e['head_speed']}, 레일 {e['conveyor_speed']}"

    if diff < 0:
        gap = round(abs(diff), 2)
        headline = f"{a['lot_id']}({cond_str(a)})가 {b['lot_id']}({cond_str(b)})보다 불량률이 {gap}%p 낮습니다."
    elif diff > 0:
        gap = round(abs(diff), 2)
        headline = f"{b['lot_id']}({cond_str(b)})가 {a['lot_id']}({cond_str(a)})보다 불량률이 {gap}%p 낮습니다."
    else:
        headline = f"{a['lot_id']}와 {b['lot_id']}의 불량률이 {a['defect_rate']}%로 동일합니다."

    same, diff_list = [], []
    for key, label, unit in CONDITION_LABELS:
        if a[key] == b[key]:
            same.append(f"{label}({a[key]}{unit})")
        else:
            diff_list.append(f"{label}({a[key]}{unit} vs {b[key]}{unit})")

    parts = [headline]
    if same:
        parts.append(f"동일 조건: {', '.join(same)}.")
    if diff_list:
        parts.append(f"차이 조건: {', '.join(diff_list)}.")
    return " ".join(parts)


def _defect_rate_diff_pp(a: dict, b: dict) -> float:
    return round(abs(a["defect_rate"] - b["defect_rate"]), 2)


def _numeric_table(a: dict, b: dict) -> str:
    a_lower = a["defect_rate"] < b["defect_rate"]
    b_lower = b["defect_rate"] < a["defect_rate"]

    def hl(is_lower):
        return ' class="highlight"' if is_lower else ""

    rows = [
        ("온도", f"{a['temperature']}°C", f"{b['temperature']}°C", False, False),
        ("헤드 속도", a["head_speed"], b["head_speed"], False, False),
        ("레일 속도", a["conveyor_speed"], b["conveyor_speed"], False, False),
        ("생산수", f"{a['quantity']}개", f"{b['quantity']}개", False, False),
        ("NG수", f"{a['ng_count']}개", f"{b['ng_count']}개", a["ng_count"] < b["ng_count"], b["ng_count"] < a["ng_count"]),
        ("불량률", f"{a['defect_rate']}%", f"{b['defect_rate']}%", a_lower, b_lower),
    ]
    for station in ["ST1", "ST2"]:
        sa, sb = a["stations"].get(station), b["stations"].get(station)
        if sa and sb:
            rows.append((f"{station} 평균", sa["mean"], sb["mean"], False, False))
            rows.append((f"{station} 표준편차", sa["std"], sb["std"], False, False))

    body = ""
    for label, va, vb, a_win, b_win in rows:
        body += f"<tr><td>{escape(str(label))}</td><td{hl(a_win)}>{escape(str(va))}</td><td{hl(b_win)}>{escape(str(vb))}</td></tr>"

    return f"""
    <table class="data-table">
      <thead><tr><th>항목</th><th>{escape(a['lot_id'])}</th><th>{escape(b['lot_id'])}</th></tr></thead>
      <tbody>{body}</tbody>
    </table>"""


def _build_compare_html(a: dict, b: dict, conclusion: str, comment: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>Lot 비교 — {escape(a['lot_id'])} vs {escape(b['lot_id'])}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f5f7; color: #1f2937; margin: 0; padding: 32px; }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin-bottom: 20px; }}
  h2 {{ font-size: 17px; margin: 28px 0 10px 0; }}
  .data-table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .data-table th, .data-table td {{ padding: 8px 12px; text-align: center; border-bottom: 1px solid #eee; font-size: 14px; }}
  .data-table th {{ background: #eef0f3; font-weight: 600; }}
  .data-table td.highlight {{ background: #d1fae5; font-weight: 700; color: #065f46; }}
  .conclusion-box {{ background: #fff7ed; border-left: 4px solid #f59e0b; padding: 14px 18px; border-radius: 6px; font-size: 15px; line-height: 1.6; }}
  .comment-box {{ background: #eef6ff; border-left: 4px solid #3b82f6; padding: 14px 18px; border-radius: 6px; margin-top: 8px; white-space: pre-wrap; line-height: 1.6; }}
</style>
</head>
<body>
<div class="container">
  <h1>Lot 비교 보고서 — {escape(a['lot_id'])} vs {escape(b['lot_id'])}</h1>

  <h2>수치 비교</h2>
  {_numeric_table(a, b)}

  <h2>규칙 기반 결론</h2>
  <div class="conclusion-box">{escape(conclusion)}</div>

  <h2>AI 해석 코멘트</h2>
  <div class="comment-box">{escape(comment)}</div>
</div>
</body>
</html>"""


def generate_compare(lot_a_id: str, lot_b_id: str):
    """비교 보고서를 생성/저장하고 (path, html, conclusion) 을 반환한다."""
    a = _get_lot_entry(lot_a_id)
    b = _get_lot_entry(lot_b_id)

    conclusion = _rule_based_conclusion(a, b)
    comment = generate_compare_comment(a, b)
    html = _build_compare_html(a, b, conclusion, comment)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(config.OUTPUT_DIR, f"COMPARE-{a['lot_id']}-{b['lot_id']}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return path, html, conclusion
