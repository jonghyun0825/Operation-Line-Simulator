"""전역 설정값. 모든 튜닝 가능한 상수는 이 파일 한 곳에서만 관리한다."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── 생산 단위 ──
BOX_SIZE = 10               # 1박스당 반제품 수
MAX_BOXES = 5                # 최대 박스 수

# ── 공정별 측정 스펙 (기준 분포) ──
ST1_SPEC = {"name": "체결토크1", "mean": 12.0, "std": 0.55, "lsl": 11.0, "usl": 13.0}  # N·m
ST2_SPEC = {"name": "체결토크2", "mean": 8.0,  "std": 0.45, "lsl": 7.2,  "usl": 8.8}   # N·m

STATIONS = {
    "ST1": ST1_SPEC,
    "ST2": ST2_SPEC,
}

# ── 생산 조건: 온도 ──
TEMP_MIN, TEMP_MAX = 20, 30      # 설정 가능 범위 (°C, 1도 단위)
TEMP_OK_RANGE = (22, 26)         # 적정 온도 범위 (이 안이면 영향 없음)
TEMP_BIAS = 0.5                  # 적정 범위 초과 시 측정값 +0.5, 미달 시 -0.5
TEMP_DEFAULT = 24

# ── 생산 조건: 헤드 속도 (3단계 프리셋) ──
# 레일(이송) 속도는 조절 기능 제거 — 이송 시간은 INDEX_SEC 고정값을 그대로 사용한다.
HEAD_SPEED_PRESETS = {
    "느림": {"time_factor": 1.3, "std_factor": 0.9},
    "보통": {"time_factor": 1.0, "std_factor": 1.0},
    "빠름": {"time_factor": 0.6, "std_factor": 1.5},
}
SPEED_DEFAULT = "보통"

# ── 택트 타이밍 기준값 (초) ──
HEAD_DOWN_SEC = 0.4
FASTEN_SEC = 0.6
HEAD_UP_SEC = 0.4
INDEX_SEC = 0.8

# ── 파일 경로 ──
OUTPUT_DIR = "./output"                    # lots_index.json 등 내부 데이터 전용 (사용자용 산출물 아님)
LOTS_INDEX = "./output/lots_index.json"

# 엑셀(.xlsx)·보고서(HTML) 저장 위치 — 프로젝트 폴더 기준 상대경로라 OS/설치 위치에 상관없이 동작한다
# (실행 시 현재 작업 디렉터리가 프로젝트 루트라고 가정 — OUTPUT_DIR과 동일한 규칙).
EXCEL_DIR = "./엑셀 데이터"
REPORT_DIR = "./보고서"

# ── LLM (환경변수에서 읽기, .env 파일 지원) ──
LLM_BASE_URL = os.environ.get("LLM_BASE_URL")
LLM_MODEL = os.environ.get("LLM_MODEL")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "none")


def temp_bias(temperature: int) -> float:
    """적정 범위를 벗어난 온도에 대한 측정값 치우침을 반환한다."""
    lo, hi = TEMP_OK_RANGE
    if temperature > hi:
        return TEMP_BIAS
    if temperature < lo:
        return -TEMP_BIAS
    return 0.0


def tact_times(head_speed: str) -> dict:
    """조건 배율이 반영된 실제 택트 구간별 시간(초)을 계산한다.
    배율 계산 로직은 이 함수(백엔드) 한 곳에만 존재한다.
    이송(index_sec)은 레일 속도 조절 기능이 없으므로 INDEX_SEC 고정값을 그대로 쓴다."""
    head = HEAD_SPEED_PRESETS[head_speed]
    tf = head["time_factor"]
    return {
        "head_down_sec": round(HEAD_DOWN_SEC * tf, 4),
        "fasten_sec": round(FASTEN_SEC * tf, 4),
        "head_up_sec": round(HEAD_UP_SEC * tf, 4),
        "index_sec": INDEX_SEC,
    }
