"""F7 Lot 비교 기능: 수치 표(파이썬) + 규칙 기반 결론 문장(파이썬) + LLM 해석 3층 구조.

한/영 전환은 report.py와 동일한 방식(data-i18n + static/i18n.js)을 쓴다. 규칙 기반 결론 문장은
파이썬이 한국어/영어 버전을 각각 조립해 dict로 만들고, data-i18n으로 토글한다. AI 해석·개선 권고도
report.py와 동일하게 llm_client.py가 두 언어를 각각 생성한다.
"""
import json
import os
from html import escape

import config
import report
from llm_client import generate_compare_comment

CONDITION_LABELS = [
    ("temperature", "온도", "Temperature", "°C"),
    ("head_speed", "헤드 속도", "Head Speed", ""),
]

STATIC_I18N = {
    "numeric_compare_title": {"ko": "수치 비교", "en": "Numeric Comparison"},
    "th_item": {"ko": "항목", "en": "Item"},
    "row_temp": {"ko": "온도", "en": "Temperature"},
    "row_head_speed": {"ko": "헤드 속도", "en": "Head Speed"},
    "row_qty": {"ko": "생산수", "en": "Quantity"},
    "row_ng_count": {"ko": "NG수", "en": "NG Count"},
    "row_defect_rate": {"ko": "불량률", "en": "Defect Rate"},
    "row_st1_mean": {"ko": "ST1 평균", "en": "ST1 Mean"},
    "row_st1_std": {"ko": "ST1 표준편차", "en": "ST1 Std Dev"},
    "row_st2_mean": {"ko": "ST2 평균", "en": "ST2 Mean"},
    "row_st2_std": {"ko": "ST2 표준편차", "en": "ST2 Std Dev"},
    "conclusion_title": {"ko": "규칙 기반 결론", "en": "Rule-Based Conclusion"},
    "ai_comment_title": {"ko": "AI 해석 코멘트", "en": "AI Interpretation"},
    "recommend_title": {"ko": "개선 권고", "en": "Recommendation"},
}


def _get_lot_entry(lot_id: str) -> dict:
    lots = {e["lot_id"]: e for e in report.list_completed_lots()}
    if lot_id not in lots:
        raise ValueError(f"완료된 Lot이 아니거나 존재하지 않는 Lot ID입니다: {lot_id}")
    return lots[lot_id]


def _speed_en(ko_value: str) -> str:
    return report.SPEED_LABEL_EN.get(ko_value, ko_value)


def _rule_based_conclusion(a: dict, b: dict) -> dict:
    """규칙 기반 결론 문장을 한국어/영어 두 버전으로 조립해 {"ko", "en"}로 반환한다."""
    diff = round(a["defect_rate"] - b["defect_rate"], 2)  # a 기준 b와의 차이

    def cond_ko(e):
        return f"{e['temperature']}°C, 헤드 {e['head_speed']}"

    def cond_en(e):
        return f"{e['temperature']}°C, head {_speed_en(e['head_speed'])}"

    if diff < 0:
        gap = round(abs(diff), 2)
        headline_ko = f"{a['lot_id']}({cond_ko(a)})가 {b['lot_id']}({cond_ko(b)})보다 불량률이 {gap}%p 낮습니다."
        headline_en = f"{a['lot_id']} ({cond_en(a)}) has a {gap}pp lower defect rate than {b['lot_id']} ({cond_en(b)})."
    elif diff > 0:
        gap = round(abs(diff), 2)
        headline_ko = f"{b['lot_id']}({cond_ko(b)})가 {a['lot_id']}({cond_ko(a)})보다 불량률이 {gap}%p 낮습니다."
        headline_en = f"{b['lot_id']} ({cond_en(b)}) has a {gap}pp lower defect rate than {a['lot_id']} ({cond_en(a)})."
    else:
        headline_ko = f"{a['lot_id']}와 {b['lot_id']}의 불량률이 {a['defect_rate']}%로 동일합니다."
        headline_en = f"{a['lot_id']} and {b['lot_id']} have the same defect rate ({a['defect_rate']}%)."

    same_ko, diff_ko, same_en, diff_en = [], [], [], []
    for key, label_ko, label_en, unit in CONDITION_LABELS:
        a_val_en = _speed_en(a[key]) if key == "head_speed" else a[key]
        b_val_en = _speed_en(b[key]) if key == "head_speed" else b[key]
        if a[key] == b[key]:
            same_ko.append(f"{label_ko}({a[key]}{unit})")
            same_en.append(f"{label_en}({a_val_en}{unit})")
        else:
            diff_ko.append(f"{label_ko}({a[key]}{unit} vs {b[key]}{unit})")
            diff_en.append(f"{label_en}({a_val_en}{unit} vs {b_val_en}{unit})")

    parts_ko = [headline_ko]
    if same_ko:
        parts_ko.append(f"동일 조건: {', '.join(same_ko)}.")
    if diff_ko:
        parts_ko.append(f"차이 조건: {', '.join(diff_ko)}.")

    parts_en = [headline_en]
    if same_en:
        parts_en.append(f"Same conditions: {', '.join(same_en)}.")
    if diff_en:
        parts_en.append(f"Different conditions: {', '.join(diff_en)}.")

    return {"ko": " ".join(parts_ko), "en": " ".join(parts_en)}


def _numeric_table(a: dict, b: dict) -> str:
    a_lower = a["defect_rate"] < b["defect_rate"]
    b_lower = b["defect_rate"] < a["defect_rate"]

    def hl(is_lower):
        return ' class="highlight"' if is_lower else ""

    rows = [
        ("row_temp", "온도", f"{a['temperature']}°C", f"{b['temperature']}°C", False, False, None),
        ("row_head_speed", "헤드 속도", a["head_speed"], b["head_speed"], False, False, "head"),
        ("row_qty", "생산수", f"{a['quantity']}개", f"{b['quantity']}개", False, False, "qty"),
        ("row_ng_count", "NG수", f"{a['ng_count']}개", f"{b['ng_count']}개", a["ng_count"] < b["ng_count"], b["ng_count"] < a["ng_count"], "ng"),
        ("row_defect_rate", "불량률", f"{a['defect_rate']}%", f"{b['defect_rate']}%", a_lower, b_lower, None),
    ]
    for station, mean_key, mean_label, std_key, std_label in [
        ("ST1", "row_st1_mean", "ST1 평균", "row_st1_std", "ST1 표준편차"),
        ("ST2", "row_st2_mean", "ST2 평균", "row_st2_std", "ST2 표준편차"),
    ]:
        sa, sb = a["stations"].get(station), b["stations"].get(station)
        if sa and sb:
            rows.append((mean_key, mean_label, sa["mean"], sb["mean"], False, False, None))
            rows.append((std_key, std_label, sa["std"], sb["std"], False, False, None))

    body = ""
    for label_key, label_text, va, vb, a_win, b_win, kind in rows:
        if kind:
            va_html = f'<td{hl(a_win)} data-i18n="val_{kind}_a">{escape(str(va))}</td>'
            vb_html = f'<td{hl(b_win)} data-i18n="val_{kind}_b">{escape(str(vb))}</td>'
        else:
            va_html = f"<td{hl(a_win)}>{escape(str(va))}</td>"
            vb_html = f"<td{hl(b_win)}>{escape(str(vb))}</td>"
        body += f'<tr><td data-i18n="{label_key}">{label_text}</td>{va_html}{vb_html}</tr>'

    return f"""
    <table class="data-table">
      <thead><tr><th data-i18n="th_item">항목</th><th>{escape(a['lot_id'])}</th><th>{escape(b['lot_id'])}</th></tr></thead>
      <tbody>{body}</tbody>
    </table>"""


def _build_i18n_dict(a: dict, b: dict, conclusion: dict) -> dict:
    dyn = {
        "page_title": {
            "ko": f"Lot 비교 — {a['lot_id']} vs {b['lot_id']}",
            "en": f"Lot Comparison — {a['lot_id']} vs {b['lot_id']}",
        },
        "compare_h1": {
            "ko": f"Lot 비교 보고서 — {a['lot_id']} vs {b['lot_id']}",
            "en": f"Lot Comparison Report — {a['lot_id']} vs {b['lot_id']}",
        },
        "conclusion": conclusion,
        "val_head_a": {"ko": a["head_speed"], "en": _speed_en(a["head_speed"])},
        "val_head_b": {"ko": b["head_speed"], "en": _speed_en(b["head_speed"])},
        "val_qty_a": {"ko": f"{a['quantity']}개", "en": f"{a['quantity']} units"},
        "val_qty_b": {"ko": f"{b['quantity']}개", "en": f"{b['quantity']} units"},
        "val_ng_a": {"ko": f"{a['ng_count']}개", "en": f"{a['ng_count']} units"},
        "val_ng_b": {"ko": f"{b['ng_count']}개", "en": f"{b['ng_count']} units"},
    }
    return {**STATIC_I18N, **dyn}


def _build_compare_html(a: dict, b: dict, conclusion: dict, comment: dict) -> str:
    i18n_dict = _build_i18n_dict(a, b, conclusion)
    i18n_dict.update(report.ai_comment_i18n_entries(comment))
    i18n_json = json.dumps(i18n_dict, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title data-i18n="page_title">Lot 비교 — {escape(a['lot_id'])} vs {escape(b['lot_id'])}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f5f7; color: #1f2937; margin: 0; padding: 32px; }}
  .container {{ max-width: 960px; margin: 0 auto; position: relative; }}
  .lang-toggle {{ position: absolute; top: 0; right: 0; padding: 8px 16px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; color: #111827; font-size: 13px; font-weight: 600; cursor: pointer; }}
  h1 {{ font-size: 22px; margin-bottom: 20px; padding-right: 100px; }}
  h2 {{ font-size: 17px; margin: 28px 0 10px 0; display: flex; align-items: baseline; gap: 8px; }}
  .data-table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .data-table th, .data-table td {{ padding: 8px 12px; text-align: center; border-bottom: 1px solid #eee; font-size: 14px; }}
  .data-table th {{ background: #eef0f3; font-weight: 600; }}
  .data-table td.highlight {{ background: #d1fae5; font-weight: 700; color: #065f46; }}
  .conclusion-box {{ background: #fff7ed; border-left: 4px solid #f59e0b; padding: 14px 18px; border-radius: 6px; font-size: 15px; line-height: 1.6; }}
  .comment-box {{ background: #eef6ff; border-left: 4px solid #3b82f6; padding: 14px 18px; border-radius: 6px; margin-top: 8px; white-space: pre-wrap; line-height: 1.6; }}
  .recommend-box {{ background: #fff7ed; border: 1px solid #fdba74; border-left: 4px solid #f97316; padding: 14px 18px; border-radius: 6px; margin-top: 10px; white-space: pre-wrap; line-height: 1.6; }}
  .recommend-title {{ font-weight: 700; color: #9a3412; margin-bottom: 4px; }}
</style>
</head>
<body>
<div class="container">
  <button id="langToggleBtn" class="lang-toggle" type="button">EN</button>
  <h1 data-i18n="compare_h1">Lot 비교 보고서 — {escape(a['lot_id'])} vs {escape(b['lot_id'])}</h1>

  <h2 data-i18n="numeric_compare_title">수치 비교</h2>
  {_numeric_table(a, b)}

  <h2 data-i18n="conclusion_title">규칙 기반 결론</h2>
  <div class="conclusion-box" data-i18n="conclusion">{escape(conclusion['ko'])}</div>

  <h2 data-i18n="ai_comment_title">AI 해석 코멘트</h2>
  {report.render_ai_comment_block(comment)}
</div>
<script src="/static/i18n.js"></script>
<script>
  i18nSetup({i18n_json});
</script>
</body>
</html>"""


def generate_compare(lot_a_id: str, lot_b_id: str):
    """비교 보고서를 생성/저장하고 (path, html, conclusion) 을 반환한다."""
    a = _get_lot_entry(lot_a_id)
    b = _get_lot_entry(lot_b_id)

    conclusion = _rule_based_conclusion(a, b)
    comment = generate_compare_comment(a, b)
    html = _build_compare_html(a, b, conclusion, comment)

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = os.path.join(config.REPORT_DIR, f"COMPARE-{a['lot_id']}-{b['lot_id']}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return path, html, conclusion
