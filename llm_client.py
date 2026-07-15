"""사내 gpt-oss 서버(OpenAI 호환 API) 연동. 실패해도 파이프라인이 죽지 않는다."""
import json

import config

try:
    from openai import OpenAI
except ImportError:  # openai 패키지가 없는 극단적 상황도 방어
    OpenAI = None

FAIL_MESSAGE = "AI 코멘트 생성 실패"

LOT_SYSTEM_PROMPT = (
    "당신은 제조 공정 품질 데이터를 해석하는 어시스턴트입니다. "
    "숫자를 새로 만들거나 계산하지 말고, 제공된 집계 수치를 근거로 해석과 권고만 작성하세요. "
    "생산 조건(온도·헤드 속도·레일 속도)과 결과(불량률, 공정별 통계)의 연관 가능성을 언급하세요. "
    "한국어로 3~5문장으로 작성하세요."
)

COMPARE_SYSTEM_PROMPT = (
    "당신은 제조 공정 품질 데이터를 비교 해석하는 어시스턴트입니다. "
    "숫자를 새로 만들거나 계산하지 말고, 제공된 두 Lot의 집계 수치만 근거로 삼으세요. "
    "어떤 생산 조건 차이가 결과 차이에 기여했을 가능성이 있는지 해석하되, "
    "단일 비교는 엄밀한 인과 증명이 아니므로 단정적 표현 대신 가능성 서술('~일 가능성이 있습니다' 등)을 사용하세요. "
    "한국어로 3~5문장으로 작성하세요."
)


def _get_client():
    if OpenAI is None or not config.LLM_BASE_URL or not config.LLM_MODEL:
        return None
    return OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY or "none")


def _chat(system_prompt: str, user_payload: dict) -> str:
    client = _get_client()
    if client is None:
        print("[llm_client] LLM 미설정(LLM_BASE_URL/LLM_MODEL 없음) - 코멘트 생성을 건너뜁니다")
        return FAIL_MESSAGE
    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            timeout=20,
        )
        content = resp.choices[0].message.content
        return content.strip() if content else FAIL_MESSAGE
    except Exception as e:
        print(f"[llm_client] LLM 호출 실패: {e}")
        return FAIL_MESSAGE


def generate_lot_comment(agg: dict) -> str:
    payload = {
        "lot_id": agg["lot_id"],
        "conditions": {
            "temperature": agg["temperature"],
            "head_speed": agg["head_speed"],
            "conveyor_speed": agg["conveyor_speed"],
        },
        "quantity": agg["quantity"],
        "ok_count": agg["ok_count"],
        "ng_count": agg["ng_count"],
        "defect_rate": agg["defect_rate"],
        "stations": agg["stations"],
    }
    return _chat(LOT_SYSTEM_PROMPT, payload)


def generate_compare_comment(agg_a: dict, agg_b: dict) -> str:
    def slim(agg):
        return {
            "lot_id": agg["lot_id"],
            "conditions": {
                "temperature": agg["temperature"],
                "head_speed": agg["head_speed"],
                "conveyor_speed": agg["conveyor_speed"],
            },
            "quantity": agg["quantity"],
            "ng_count": agg["ng_count"],
            "defect_rate": agg["defect_rate"],
            "stations": agg["stations"],
        }
    payload = {"lot_a": slim(agg_a), "lot_b": slim(agg_b)}
    return _chat(COMPARE_SYSTEM_PROMPT, payload)
