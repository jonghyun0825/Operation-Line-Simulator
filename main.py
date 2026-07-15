"""FastAPI 백엔드. Phase 1의 로직 모듈(lot_manager/measurement/excel_writer/report/compare)을
6종 API로 노출한다. 동일 로직을 API 안에서 다시 구현하지 않는다."""
import os
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import compare
import config
import report
from excel_writer import ExcelWriter
from lot_manager import Lot
from measurement import generate_measurement

app = FastAPI(title="가상 조립라인 품질관리 시뮬레이터")

os.makedirs(config.OUTPUT_DIR, exist_ok=True)
os.makedirs("static", exist_ok=True)


@dataclass
class LotSession:
    lot: Lot
    writer: ExcelWriter
    report_generated: bool = False
    report_path: Optional[str] = None


ACTIVE_LOTS: Dict[str, LotSession] = {}


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # 예외가 서버 프로세스를 죽이지 않고, 항상 명확한 에러 JSON으로 응답하게 한다.
    return JSONResponse(status_code=500, content={"error": str(exc)})


# ── 요청 바디 모델 ──
class LotCreateRequest(BaseModel):
    boxes: int
    temperature: int
    head_speed: str
    conveyor_speed: str


class MeasureRequest(BaseModel):
    lot_id: str
    unit_sn: str
    station: str


class UnitCompleteRequest(BaseModel):
    lot_id: str
    unit_sn: str


# ── API ──
@app.post("/api/lot")
def create_lot(req: LotCreateRequest):
    try:
        lot = Lot.create(req.boxes, req.temperature, req.head_speed, req.conveyor_speed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    writer = ExcelWriter(lot.lot_id)
    ACTIVE_LOTS[lot.lot_id] = LotSession(lot=lot, writer=writer)

    return {"lot_id": lot.lot_id, "quantity": lot.quantity, "tact_times": lot.tact}


@app.post("/api/measure")
def measure(req: MeasureRequest):
    session = ACTIVE_LOTS.get(req.lot_id)
    if session is None:
        return JSONResponse(status_code=404, content={"error": f"Lot을 찾을 수 없습니다: {req.lot_id}"})
    if req.station not in config.STATIONS:
        return JSONResponse(status_code=400, content={"error": f"알 수 없는 공정입니다: {req.station}"})

    lot = session.lot
    value, judgment, lsl, usl, item_name = generate_measurement(req.station, lot.temperature, lot.head_speed)
    rec = lot.record_measurement(req.unit_sn, req.station, value, judgment, lsl, usl, item_name)
    session.writer.append_measurement(
        rec.seq, rec.sn, rec.station, rec.item_name,
        rec.value, rec.lsl, rec.usl, rec.judgment, rec.ts,
    )
    return {"value": value, "judgment": judgment}


@app.post("/api/unit-complete")
def unit_complete(req: UnitCompleteRequest):
    session = ACTIVE_LOTS.get(req.lot_id)
    if session is None:
        return JSONResponse(status_code=404, content={"error": f"Lot을 찾을 수 없습니다: {req.lot_id}"})

    lot = session.lot
    lot.mark_unit_complete(req.unit_sn)

    if lot.completed and not session.report_generated:
        agg = lot.aggregate()
        session.writer.write_summary(agg)
        report_path, _comment = report.generate_report(agg)
        session.report_path = report_path
        session.report_generated = True

    return {
        "completed": lot.completed,
        "completed_count": len(lot.completed_sns),
        "quantity": lot.quantity,
        "report_ready": session.report_generated,
    }


@app.get("/api/status/{lot_id}")
def get_status(lot_id: str):
    session = ACTIVE_LOTS.get(lot_id)
    if session is None:
        return JSONResponse(status_code=404, content={"error": f"Lot을 찾을 수 없습니다: {lot_id}"})

    lot = session.lot
    ng_events = [
        {"sn": m.sn, "station": m.station, "value": m.value, "ts": m.ts}
        for m in reversed(lot.ng_events)  # 최근 발생이 위로
    ]
    defect_rate = round((lot.ng_count / lot.quantity) * 100, 2) if lot.quantity else 0.0

    return {
        "lot_id": lot.lot_id,
        "conditions": {
            "temperature": lot.temperature,
            "head_speed": lot.head_speed,
            "conveyor_speed": lot.conveyor_speed,
        },
        "quantity": lot.quantity,
        "completed_count": len(lot.completed_sns),
        "ok_count": lot.ok_count,
        "ng_count": lot.ng_count,
        "defect_rate": defect_rate,
        "ng_events": ng_events,
        "completed": lot.completed,
        "report_ready": session.report_generated,
    }


@app.get("/api/report/{lot_id}")
def get_report(lot_id: str):
    path = os.path.join(config.OUTPUT_DIR, f"{lot_id}_report.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="보고서가 아직 생성되지 않았습니다")
    return FileResponse(path, media_type="text/html")


@app.get("/api/lots")
def get_lots():
    return report.list_completed_lots()


@app.get("/api/compare")
def get_compare(lot_a: str, lot_b: str):
    try:
        _path, html, _conclusion = compare.generate_compare(lot_a, lot_b)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return HTMLResponse(content=html)


# ── 정적 파일 ──
app.mount("/output", StaticFiles(directory=config.OUTPUT_DIR), name="output")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join("static", "index.html"))
