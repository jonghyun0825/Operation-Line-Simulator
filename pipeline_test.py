#!/usr/bin/env python
"""Phase 1 검증용 CLI. FastAPI 없이 전체 파이프라인을 순서대로 실행한다.

박스 수 + 생산 조건 입력 -> 수량 환산 -> SN 생성 -> 조건 반영 공식으로 두 공정
측정값 생성/판정 -> 엑셀 기록(빨간 셀 포함) -> 집계 + lots_index.json 저장
-> LLM 코멘트 -> HTML 보고서 저장까지 전부 실행한다.

예)
  python pipeline_test.py 2 --temp 24 --head 보통
  python pipeline_test.py 2 --temp 29 --head 보통
"""
import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config
import report
from excel_writer import ExcelWriter
from lot_manager import Lot
from measurement import generate_measurement


def run(boxes: int, temperature: int, head_speed: str) -> dict:
    lot = Lot.create(boxes, temperature, head_speed)
    print(f"[Lot 생성] {lot.lot_id} | 수량 {lot.quantity}개 | 온도 {temperature}C | 헤드 {head_speed}")
    print(f"[택트 시간] {lot.tact}")

    writer = ExcelWriter(lot.lot_id)

    for sn in lot.sns:
        for station in config.STATIONS:
            value, judgment, lsl, usl, item_name = generate_measurement(station, temperature, head_speed)
            rec = lot.record_measurement(sn, station, value, judgment, lsl, usl, item_name)
            writer.append_measurement(rec.sn, rec.station, rec.value, rec.judgment, rec.ts)
        lot.mark_unit_complete(sn)

    agg = lot.aggregate()
    writer.write_summary(agg)

    report_path, comment = report.generate_report(agg)

    print(f"[집계] 생산 {agg['quantity']} | OK {agg['ok_count']} | NG {agg['ng_count']} | 불량률 {agg['defect_rate']}%")
    for station, stat in agg["stations"].items():
        print(
            f"  {station}({stat['name']}) 평균={stat['mean']} 표준편차={stat['std']} "
            f"최소={stat['min']} 최대={stat['max']} NG={stat['ng_count']}"
        )
    print(f"[엑셀] {writer.path}")
    print(f"[보고서] {report_path}")
    print(f"[AI 해석/KO] {comment['analysis']['ko']}")
    print(f"[AI 해석/EN] {comment['analysis']['en']}")
    rec = comment.get("recommendation") or {}
    if rec.get("ko") or rec.get("en"):
        print(f"[AI 개선 권고/KO] {rec.get('ko')}")
        print(f"[AI 개선 권고/EN] {rec.get('en')}")
    return agg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="가상 조립라인 파이프라인 테스트 (Phase 1)")
    parser.add_argument("boxes", type=int, help=f"박스 수 (1~{config.MAX_BOXES})")
    parser.add_argument("--temp", type=int, default=config.TEMP_DEFAULT,
                         help=f"온도 ({config.TEMP_MIN}~{config.TEMP_MAX}, 기본 {config.TEMP_DEFAULT})")
    parser.add_argument("--head", type=str, default=config.SPEED_DEFAULT,
                         choices=list(config.HEAD_SPEED_PRESETS), help="헤드 속도")
    args = parser.parse_args()

    run(args.boxes, args.temp, args.head)
