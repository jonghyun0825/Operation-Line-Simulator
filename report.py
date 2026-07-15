"""Lot 완료 보고서: 파이썬 집계(F6 1단계) → LLM 코멘트(2단계) → HTML 출력(3단계).

수치는 전부 agg(dict, lot_manager.Lot.aggregate() 결과)에서 직접 렌더링한다.
LLM 출력에서는 코멘트 텍스트만 가져오고 숫자를 가져오지 않는다.

한/영 전환: 고정 라벨과 Lot별 값 모두 data-i18n 속성 + JS 사전(dict) 하나로 통일해서 처리한다
(static/i18n.js가 공통 엔진). AI가 생성하는 해석·개선 권고 문장 자체는 번역 API 없이는 자동
번역할 수 없어 한국어로만 표시되며, 영어 모드에서는 그 사실을 알리는 안내문을 덧붙인다.
"""
import json
import os
from html import escape

import config
from llm_client import generate_lot_comment

STATION_ORDER = ["ST1", "ST2"]

SPEED_LABEL_EN = {"느림": "Slow", "보통": "Normal", "빠름": "Fast"}
STATION_NAME_EN = {"체결토크1": "Fastening Torque 1", "체결토크2": "Fastening Torque 2"}

# 페이지 전체에서 값이 바뀌지 않는 고정 라벨. Lot마다 달라지는 값(제목·조건·수치 등)은
# build_html_report()에서 이 사전에 합쳐진다.
STATIC_I18N = {
    "cond_title": {"ko": "생산 조건", "en": "Production Conditions"},
    "temp_label": {"ko": "온도", "en": "Temperature"},
    "head_speed_label": {"ko": "헤드 속도", "en": "Head Speed"},
    "box_count_label": {"ko": "박스 수", "en": "Box Count"},
    "qty_label": {"ko": "생산수량", "en": "Quantity"},
    "ok_label": {"ko": "OK 수", "en": "OK Count"},
    "ng_label": {"ko": "NG 수", "en": "NG Count"},
    "defect_rate_label": {"ko": "불량률", "en": "Defect Rate"},
    "station_stats_title": {"ko": "공정별 통계", "en": "Per-Station Statistics"},
    "th_station": {"ko": "공정", "en": "Station"},
    "th_item": {"ko": "측정항목", "en": "Item"},
    "th_mean": {"ko": "평균", "en": "Mean"},
    "th_std": {"ko": "표준편차", "en": "Std Dev"},
    "th_min": {"ko": "최소", "en": "Min"},
    "th_max": {"ko": "최대", "en": "Max"},
    "th_spec": {"ko": "규격", "en": "Spec"},
    "th_ng_count": {"ko": "NG수", "en": "NG Count"},
    "ng_list_title": {"ko": "NG 목록", "en": "NG List"},
    "th_sn": {"ko": "반제품SN", "en": "Unit SN"},
    "th_ng_station": {"ko": "NG공정", "en": "NG Station"},
    "th_value": {"ko": "측정값", "en": "Value"},
    "th_occurred_at": {"ko": "발생시각", "en": "Occurred At"},
    "no_ng": {"ko": "NG 발생 없음", "en": "No NG occurred"},
    "ai_comment_title": {"ko": "AI 해석 코멘트", "en": "AI Interpretation"},
    "ai_ko_only_note": {"ko": "", "en": "(AI-generated text is written in Korean only)"},
    "recommend_title": {"ko": "개선 권고", "en": "Recommendation"},
    "download_btn": {"ko": "엑셀 파일 다운로드", "en": "Download Excel File"},
}


def _load_lots_index() -> list:
    if os.path.exists(config.LOTS_INDEX):
        with open(config.LOTS_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _lots_index_entry(agg: dict) -> dict:
    return {
        "lot_id": agg["lot_id"],
        "boxes": agg["boxes"],
        "quantity": agg["quantity"],
        "temperature": agg["temperature"],
        "head_speed": agg["head_speed"],
        "ok_count": agg["ok_count"],
        "ng_count": agg["ng_count"],
        "defect_rate": agg["defect_rate"],
        "created_at": agg["created_at"],
        "completed_at": agg["completed_at"],
        "stations": agg["stations"],
    }


def save_lot_index_entry(agg: dict) -> None:
    """완료 Lot의 조건+집계를 lots_index.json에 추가 저장한다 (서버 재시작 후에도 비교 기능 동작)."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    data = _load_lots_index()
    data = [e for e in data if e["lot_id"] != agg["lot_id"]]  # 재생성 시 중복 방지
    data.append(_lots_index_entry(agg))
    with open(config.LOTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_completed_lots() -> list:
    return _load_lots_index()


def render_ai_comment_block(comment: dict) -> str:
    """LLM 코멘트 dict({"analysis": str, "recommendation": str|None})를
    해석 문단 + (있으면) 개선 권고 강조 블록 HTML로 렌더링한다.
    recommendation이 없으면(JSON 분리 실패 등) analysis만 기존처럼 단일 문단으로 표시된다."""
    html = f'<div class="comment-box">{escape(comment["analysis"])}</div>'
    if comment.get("recommendation"):
        html += f"""
    <div class="recommend-box">
      <div class="recommend-title" data-i18n="recommend_title">개선 권고</div>
      <div>{escape(comment["recommendation"])}</div>
    </div>"""
    return html


def _condition_card(agg: dict) -> str:
    return f"""
    <div class="card cond-card">
      <h3 data-i18n="cond_title">생산 조건</h3>
      <div class="cond-grid">
        <div><span class="label" data-i18n="temp_label">온도</span><span class="value" data-i18n="cond_temp_value">{agg['temperature']}°C</span></div>
        <div><span class="label" data-i18n="head_speed_label">헤드 속도</span><span class="value" data-i18n="cond_head_value">{escape(agg['head_speed'])}</span></div>
        <div><span class="label" data-i18n="box_count_label">박스 수</span><span class="value" data-i18n="cond_box_value">{agg['boxes']}</span></div>
      </div>
    </div>"""


def _summary_cards(agg: dict) -> str:
    items = [
        ("qty_label", "생산수량", "stat_qty_value", f"{agg['quantity']}개"),
        ("ok_label", "OK 수", "stat_ok_value", f"{agg['ok_count']}개"),
        ("ng_label", "NG 수", "stat_ng_value", f"{agg['ng_count']}개"),
        ("defect_rate_label", "불량률", "stat_defect_value", f"{agg['defect_rate']}%"),
    ]
    cards = "".join(
        f'<div class="card stat-card"><div class="label" data-i18n="{label_key}">{label_text}</div>'
        f'<div class="value" data-i18n="{value_key}">{val}</div></div>'
        for label_key, label_text, value_key, val in items
    )
    return f'<div class="stat-grid">{cards}</div>'


def _station_table(agg: dict) -> str:
    rows = ""
    for station in STATION_ORDER:
        s = agg["stations"].get(station)
        if not s:
            continue
        rows += f"""
        <tr>
          <td>{station}</td><td data-i18n="station_name_{station}">{escape(s['name'])}</td>
          <td>{s['mean']}</td><td>{s['std']}</td><td>{s['min']}</td><td>{s['max']}</td>
          <td>{s['lsl']} ~ {s['usl']}</td><td>{s['ng_count']}</td>
        </tr>"""
    return f"""
    <table class="data-table">
      <thead><tr>
        <th data-i18n="th_station">공정</th><th data-i18n="th_item">측정항목</th>
        <th data-i18n="th_mean">평균</th><th data-i18n="th_std">표준편차</th>
        <th data-i18n="th_min">최소</th><th data-i18n="th_max">최대</th>
        <th data-i18n="th_spec">규격</th><th data-i18n="th_ng_count">NG수</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _ng_table(agg: dict) -> str:
    events = agg["ng_events"]
    if not events:
        return '<p class="empty" data-i18n="no_ng">NG 발생 없음</p>'
    rows = "".join(
        f"<tr><td>{escape(e['sn'])}</td><td>{escape(e['station'])}</td><td>{e['value']}</td><td>{escape(e['ts'])}</td></tr>"
        for e in reversed(events)  # 최근 발생이 위로
    )
    return f"""
    <table class="data-table">
      <thead><tr>
        <th data-i18n="th_sn">반제품SN</th><th data-i18n="th_ng_station">NG공정</th>
        <th data-i18n="th_value">측정값</th><th data-i18n="th_occurred_at">발생시각</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _build_i18n_dict(agg: dict) -> dict:
    """고정 라벨(STATIC_I18N)에 이 Lot에서만 쓰이는 동적 값을 합친 최종 사전을 만든다."""
    dyn = {
        "page_title": {"ko": f"{agg['lot_id']} 품질 보고서", "en": f"{agg['lot_id']} Quality Report"},
        "report_h1": {"ko": f"Lot 품질 보고서 — {agg['lot_id']}", "en": f"Lot Quality Report — {agg['lot_id']}"},
        "report_subtitle": {
            "ko": f"생성 {agg['created_at']} · 완료 {agg['completed_at']}",
            "en": f"Created {agg['created_at']} · Completed {agg['completed_at']}",
        },
        "cond_temp_value": {"ko": f"{agg['temperature']}°C", "en": f"{agg['temperature']}°C"},
        "cond_head_value": {
            "ko": agg["head_speed"],
            "en": SPEED_LABEL_EN.get(agg["head_speed"], agg["head_speed"]),
        },
        "cond_box_value": {"ko": str(agg["boxes"]), "en": str(agg["boxes"])},
        "stat_qty_value": {"ko": f"{agg['quantity']}개", "en": f"{agg['quantity']} units"},
        "stat_ok_value": {"ko": f"{agg['ok_count']}개", "en": f"{agg['ok_count']} units"},
        "stat_ng_value": {"ko": f"{agg['ng_count']}개", "en": f"{agg['ng_count']} units"},
        "stat_defect_value": {"ko": f"{agg['defect_rate']}%", "en": f"{agg['defect_rate']}%"},
    }
    for station in STATION_ORDER:
        s = agg["stations"].get(station)
        if s:
            dyn[f"station_name_{station}"] = {
                "ko": s["name"],
                "en": STATION_NAME_EN.get(s["name"], s["name"]),
            }
    return {**STATIC_I18N, **dyn}


def build_html_report(agg: dict, comment: dict) -> str:
    excel_href = f"/excel-files/{agg['lot_id']}.xlsx"
    i18n_dict = _build_i18n_dict(agg)
    i18n_json = json.dumps(i18n_dict, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title data-i18n="page_title">{escape(agg['lot_id'])} 품질 보고서</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f5f7; color: #1f2937; margin: 0; padding: 32px; }}
  .container {{ max-width: 960px; margin: 0 auto; position: relative; }}
  .lang-toggle {{ position: absolute; top: 0; right: 0; padding: 8px 16px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; color: #111827; font-size: 13px; font-weight: 600; cursor: pointer; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; padding-right: 100px; }}
  .subtitle {{ color: #6b7280; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .cond-card {{ margin-bottom: 20px; }}
  .cond-card h3 {{ margin: 0 0 12px 0; font-size: 15px; color: #374151; }}
  .cond-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  .cond-grid .label {{ display:block; font-size: 12px; color: #6b7280; }}
  .cond-grid .value {{ display:block; font-size: 18px; font-weight: 600; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
  .stat-card .label {{ font-size: 12px; color: #6b7280; }}
  .stat-card .value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
  h2 {{ font-size: 17px; margin: 28px 0 10px 0; display: flex; align-items: baseline; gap: 8px; }}
  .data-table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .data-table th, .data-table td {{ padding: 8px 12px; text-align: center; border-bottom: 1px solid #eee; font-size: 14px; }}
  .data-table th {{ background: #eef0f3; font-weight: 600; }}
  .empty {{ color: #9ca3af; }}
  .comment-box {{ background: #eef6ff; border-left: 4px solid #3b82f6; padding: 14px 18px; border-radius: 6px; margin-top: 8px; white-space: pre-wrap; line-height: 1.6; }}
  .recommend-box {{ background: #fff7ed; border: 1px solid #fdba74; border-left: 4px solid #f97316; padding: 14px 18px; border-radius: 6px; margin-top: 10px; white-space: pre-wrap; line-height: 1.6; }}
  .recommend-title {{ font-weight: 700; color: #9a3412; margin-bottom: 4px; }}
  .ai-note {{ font-size: 12px; color: #9ca3af; font-weight: 400; }}
  .download {{ display: inline-block; margin-top: 24px; padding: 10px 18px; background: #111827; color: #fff; text-decoration: none; border-radius: 6px; }}
</style>
</head>
<body>
<div class="container">
  <button id="langToggleBtn" class="lang-toggle" type="button">EN</button>
  <h1 data-i18n="report_h1">Lot 품질 보고서 — {escape(agg['lot_id'])}</h1>
  <div class="subtitle" data-i18n="report_subtitle">생성 {escape(agg['created_at'])} · 완료 {escape(agg['completed_at'])}</div>

  {_condition_card(agg)}
  {_summary_cards(agg)}

  <h2 data-i18n="station_stats_title">공정별 통계</h2>
  {_station_table(agg)}

  <h2 data-i18n="ng_list_title">NG 목록</h2>
  {_ng_table(agg)}

  <h2><span data-i18n="ai_comment_title">AI 해석 코멘트</span><span class="ai-note" data-i18n="ai_ko_only_note"></span></h2>
  {render_ai_comment_block(comment)}

  <a class="download" href="{escape(excel_href)}" download data-i18n="download_btn">엑셀 파일 다운로드</a>
</div>
<script src="/static/i18n.js"></script>
<script>
  i18nSetup({i18n_json});
</script>
</body>
</html>"""


def generate_report(agg: dict):
    """1) LLM 코멘트, 2) lots_index 저장, 3) HTML 저장까지 수행하고 (경로, 코멘트)를 반환한다."""
    comment = generate_lot_comment(agg)
    save_lot_index_entry(agg)
    html = build_html_report(agg, comment)

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = os.path.join(config.REPORT_DIR, f"{agg['lot_id']}_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return path, comment
