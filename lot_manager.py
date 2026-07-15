"""Lot 상태(진행 중 데이터)를 소유하는 도메인 모델.

Phase 1의 pipeline_test.py와 Phase 2의 main.py(API)가 이 모듈을 공유해서
"Lot 생성 → 측정 기록 → 집계" 로직이 두 곳에서 따로 구현되지 않도록 한다.
"""
import glob
import os
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import config


def next_lot_id(now: Optional[datetime] = None) -> str:
    """output 디렉터리의 기존 xlsx 파일을 스캔해 오늘자 다음 순번을 부여한다.
    (완료되지 않은 Lot도 파일이 이미 생성돼 있으므로 재시작 후에도 번호가 겹치지 않는다)"""
    now = now or datetime.now()
    date_str = now.strftime("%Y%m%d")
    os.makedirs(config.EXCEL_DIR, exist_ok=True)
    pattern = os.path.join(config.EXCEL_DIR, f"LOT-{date_str}-*.xlsx")
    max_n = 0
    for path in glob.glob(pattern):
        m = re.search(r"LOT-(\d{8})-(\d{3})\.xlsx$", os.path.basename(path))
        if m and m.group(1) == date_str:
            max_n = max(max_n, int(m.group(2)))
    return f"LOT-{date_str}-{max_n + 1:03d}"


@dataclass
class MeasurementRecord:
    seq: int
    sn: str
    station: str
    item_name: str
    value: float
    lsl: float
    usl: float
    judgment: str
    ts: str


@dataclass
class Lot:
    lot_id: str
    boxes: int
    quantity: int
    temperature: int
    head_speed: str
    tact: dict
    created_at: str
    sns: List[str] = field(default_factory=list)
    measurements: List[MeasurementRecord] = field(default_factory=list)
    unit_station_judgment: Dict[str, Dict[str, str]] = field(default_factory=dict)
    completed_sns: List[str] = field(default_factory=list)
    completed: bool = False
    completed_at: Optional[str] = None
    _seq_counter: int = 0

    @classmethod
    def create(cls, boxes: int, temperature: int, head_speed: str) -> "Lot":
        if not (1 <= boxes <= config.MAX_BOXES):
            raise ValueError(f"boxes는 1~{config.MAX_BOXES} 범위여야 합니다 (받은 값: {boxes})")
        if not (config.TEMP_MIN <= temperature <= config.TEMP_MAX):
            raise ValueError(f"temperature는 {config.TEMP_MIN}~{config.TEMP_MAX} 범위여야 합니다 (받은 값: {temperature})")
        if head_speed not in config.HEAD_SPEED_PRESETS:
            raise ValueError(f"head_speed는 {list(config.HEAD_SPEED_PRESETS)} 중 하나여야 합니다")

        quantity = boxes * config.BOX_SIZE
        lot_id = next_lot_id()
        sns = [f"SN-{i:04d}" for i in range(1, quantity + 1)]
        tact = config.tact_times(head_speed)

        lot = cls(
            lot_id=lot_id,
            boxes=boxes,
            quantity=quantity,
            temperature=temperature,
            head_speed=head_speed,
            tact=tact,
            created_at=datetime.now().isoformat(timespec="seconds"),
            sns=sns,
        )
        lot.unit_station_judgment = {sn: {} for sn in sns}
        return lot

    def record_measurement(self, sn: str, station: str, value: float, judgment: str,
                            lsl: float, usl: float, item_name: str) -> MeasurementRecord:
        self._seq_counter += 1
        rec = MeasurementRecord(
            seq=self._seq_counter, sn=sn, station=station, item_name=item_name,
            value=value, lsl=lsl, usl=usl, judgment=judgment,
            ts=datetime.now().isoformat(timespec="seconds"),
        )
        self.measurements.append(rec)
        self.unit_station_judgment.setdefault(sn, {})[station] = judgment
        return rec

    def mark_unit_complete(self, sn: str) -> None:
        if sn not in self.completed_sns:
            self.completed_sns.append(sn)
        if len(self.completed_sns) >= self.quantity:
            self.completed = True
            self.completed_at = datetime.now().isoformat(timespec="seconds")

    def unit_judgment(self, sn: str) -> Optional[str]:
        """양쪽 공정이 모두 측정된 반제품만 최종 판정을 반환한다 (아니면 None)."""
        j = self.unit_station_judgment.get(sn, {})
        if len(j) < len(config.STATIONS):
            return None
        return "NG" if any(v == "NG" for v in j.values()) else "OK"

    @property
    def ok_count(self) -> int:
        return sum(1 for sn in self.sns if self.unit_judgment(sn) == "OK")

    @property
    def ng_count(self) -> int:
        return sum(1 for sn in self.sns if self.unit_judgment(sn) == "NG")

    @property
    def ng_events(self) -> List[MeasurementRecord]:
        """측정 이벤트 단위 NG 목록 (한 SN이 두 공정 모두 NG면 2건으로 집계됨)."""
        return [m for m in self.measurements if m.judgment == "NG"]

    def aggregate(self) -> dict:
        """엑셀 Lot요약 / 보고서 / lots_index.json이 공유하는 단일 집계 소스."""
        stations_stat = {}
        for station, spec in config.STATIONS.items():
            vals = [m.value for m in self.measurements if m.station == station]
            ng_count = sum(1 for m in self.measurements if m.station == station and m.judgment == "NG")
            if vals:
                mean = round(sum(vals) / len(vals), 3)
                std = round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0
                vmin, vmax = min(vals), max(vals)
            else:
                mean = std = vmin = vmax = 0.0
            stations_stat[station] = {
                "name": spec["name"], "lsl": spec["lsl"], "usl": spec["usl"],
                "mean": mean, "std": std, "min": vmin, "max": vmax,
                "ng_count": ng_count, "count": len(vals),
            }

        ng_events = [
            {"sn": m.sn, "station": m.station, "value": m.value, "ts": m.ts}
            for m in self.ng_events
        ]

        ok, ng = self.ok_count, self.ng_count
        defect_rate = round((ng / self.quantity) * 100, 2) if self.quantity else 0.0

        return {
            "lot_id": self.lot_id,
            "boxes": self.boxes,
            "quantity": self.quantity,
            "temperature": self.temperature,
            "head_speed": self.head_speed,
            "tact": self.tact,
            "created_at": self.created_at,
            "completed_at": self.completed_at or datetime.now().isoformat(timespec="seconds"),
            "ok_count": ok,
            "ng_count": ng,
            "defect_rate": defect_rate,
            "stations": stations_stat,
            "ng_events": ng_events,
        }
