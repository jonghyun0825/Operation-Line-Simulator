"""Lot 완료 보고서: 파이썬 집계(F6 1단계) → LLM 코멘트(2단계) → HTML 출력(3단계).

수치는 전부 agg(dict, lot_manager.Lot.aggregate() 결과)에서 직접 렌더링한다.
LLM 출력에서는 코멘트 텍스트만 가져오고 숫자를 가져오지 않는다.
"""
import json
import os
from html import escape

import config
from llm_client import generate_lot_comment

STATION_ORDER = ["ST1", "ST2"]


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
        "conveyor_speed": agg["conveyor_speed"],
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


def _condition_card(agg: dict) -> str:
    return f"""
    <div class="card cond-card">
      <h3>생산 조건</h3>
      <div class="cond-grid">
        <div><span class="label">온도</span><span class="value">{agg['temperature']}°C</span></div>
        <div><span class="label">헤드 속도</span><span class="value">{escape(agg['head_speed'])}</span></div>
        <div><span class="label">레일 속도</span><span class="value">{escape(agg['conveyor_speed'])}</span></div>
        <div><span class="label">박스 수</span><span class="value">{agg['boxes']}</span></div>
      </div>
    </div>"""


def _summary_cards(agg: dict) -> str:
    items = [
        ("생산수량", f"{agg['quantity']}개"),
        ("OK 수", f"{agg['ok_count']}개"),
        ("NG 수", f"{agg['ng_count']}개"),
        ("불량률", f"{agg['defect_rate']}%"),
    ]
    cards = "".join(
        f'<div class="card stat-card"><div class="label">{label}</div><div class="value">{val}</div></div>'
        for label, val in items
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
          <td>{station}</td><td>{escape(s['name'])}</td>
          <td>{s['mean']}</td><td>{s['std']}</td><td>{s['min']}</td><td>{s['max']}</td>
          <td>{s['lsl']} ~ {s['usl']}</td><td>{s['ng_count']}</td>
        </tr>"""
    return f"""
    <table class="data-table">
      <thead><tr><th>공정</th><th>측정항목</th><th>평균</th><th>표준편차</th><th>최소</th><th>최대</th><th>규격</th><th>NG수</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _ng_table(agg: dict) -> str:
    events = agg["ng_events"]
    if not events:
        return '<p class="empty">NG 발생 없음</p>'
    rows = "".join(
        f"<tr><td>{escape(e['sn'])}</td><td>{escape(e['station'])}</td><td>{e['value']}</td><td>{escape(e['ts'])}</td></tr>"
        for e in reversed(events)  # 최근 발생이 위로
    )
    return f"""
    <table class="data-table">
      <thead><tr><th>반제품SN</th><th>NG공정</th><th>측정값</th><th>발생시각</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def build_html_report(agg: dict, comment: str) -> str:
    excel_href = f"/output/{agg['lot_id']}.xlsx"
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{escape(agg['lot_id'])} 품질 보고서</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f5f7; color: #1f2937; margin: 0; padding: 32px; }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; }}
  .subtitle {{ color: #6b7280; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .cond-card {{ margin-bottom: 20px; }}
  .cond-card h3 {{ margin: 0 0 12px 0; font-size: 15px; color: #374151; }}
  .cond-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .cond-grid .label {{ display:block; font-size: 12px; color: #6b7280; }}
  .cond-grid .value {{ display:block; font-size: 18px; font-weight: 600; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
  .stat-card .label {{ font-size: 12px; color: #6b7280; }}
  .stat-card .value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
  h2 {{ font-size: 17px; margin: 28px 0 10px 0; }}
  .data-table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .data-table th, .data-table td {{ padding: 8px 12px; text-align: center; border-bottom: 1px solid #eee; font-size: 14px; }}
  .data-table th {{ background: #eef0f3; font-weight: 600; }}
  .empty {{ color: #9ca3af; }}
  .comment-box {{ background: #eef6ff; border-left: 4px solid #3b82f6; padding: 14px 18px; border-radius: 6px; margin-top: 8px; white-space: pre-wrap; line-height: 1.6; }}
  .download {{ display: inline-block; margin-top: 24px; padding: 10px 18px; background: #111827; color: #fff; text-decoration: none; border-radius: 6px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Lot 품질 보고서 — {escape(agg['lot_id'])}</h1>
  <div class="subtitle">생성 {escape(agg['created_at'])} · 완료 {escape(agg['completed_at'])}</div>

  {_condition_card(agg)}
  {_summary_cards(agg)}

  <h2>공정별 통계</h2>
  {_station_table(agg)}

  <h2>NG 목록</h2>
  {_ng_table(agg)}

  <h2>AI 해석 코멘트</h2>
  <div class="comment-box">{escape(comment)}</div>

  <a class="download" href="{escape(excel_href)}" download>엑셀 파일 다운로드</a>
</div>
</body>
</html>"""


def generate_report(agg: dict):
    """1) LLM 코멘트, 2) lots_index 저장, 3) HTML 저장까지 수행하고 (경로, 코멘트)를 반환한다."""
    comment = generate_lot_comment(agg)
    save_lot_index_entry(agg)
    html = build_html_report(agg, comment)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(config.OUTPUT_DIR, f"{agg['lot_id']}_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return path, comment
