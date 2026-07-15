"""사내 gpt-oss 서버(OpenAI 호환 API) 연동. 실패해도 파이프라인이 죽지 않는다.

LLM에는 "해석(analysis)"과 "개선 권고(recommendation)"를 분리한 JSON으로만 응답하도록 요청한다.
JSON 파싱이 실패하면(모델이 형식을 안 지키는 등) 전체 텍스트를 기존처럼 단일 문단으로 표시하는
폴백을 사용한다 — 파싱 실패가 보고서 생성 자체를 막지 않는다.

한/영 두 언어 버전을 동시에 만든다: 번역 API 없이, 같은 LLM에게 한국어/영어로 각각 한 번씩
(동일한 집계 수치를 근거로) 독립적으로 써 달라고 요청한다. 두 호출은 스레드로 병렬 실행해서
전체 대기시간이 순차 호출 대비 거의 늘지 않게 한다.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import config

try:
    from openai import OpenAI
except ImportError:  # openai 패키지가 없는 극단적 상황도 방어
    OpenAI = None

FAIL_MESSAGE = {"ko": "AI 코멘트 생성 실패", "en": "AI comment generation failed"}

JSON_RESPONSE_INSTRUCTION_KO = (
    " 다른 설명 없이 반드시 다음 JSON 형식으로만 응답하세요: "
    '{"analysis": "결과 해석 2~3문장", "recommendation": "개선 권고 1~2문장"}'
)
JSON_RESPONSE_INSTRUCTION_EN = (
    " Respond with nothing but the following JSON format: "
    '{"analysis": "2-3 sentence interpretation of the results", '
    '"recommendation": "1-2 sentence improvement recommendation"}'
)

LOT_SYSTEM_PROMPT_KO = (
    "당신은 제조 공정 품질 데이터를 해석하는 어시스턴트입니다. "
    "숫자를 새로 만들거나 계산하지 말고, 제공된 집계 수치를 근거로 해석과 권고만 작성하세요. "
    "생산 조건(온도·헤드 속도)과 결과(불량률, 공정별 통계)의 연관 가능성을 언급하세요. "
    "한국어로 작성하세요." + JSON_RESPONSE_INSTRUCTION_KO
)
LOT_SYSTEM_PROMPT_EN = (
    "You are an assistant that interprets manufacturing process quality data. "
    "Do not invent or calculate new numbers — base your analysis and recommendation only on "
    "the provided aggregate figures. Mention the possible relationship between production "
    "conditions (temperature, head speed) and the results (defect rate, per-station stats). "
    "Write in English." + JSON_RESPONSE_INSTRUCTION_EN
)

COMPARE_SYSTEM_PROMPT_KO = (
    "당신은 제조 공정 품질 데이터를 비교 해석하는 어시스턴트입니다. "
    "숫자를 새로 만들거나 계산하지 말고, 제공된 두 Lot의 집계 수치만 근거로 삼으세요. "
    "어떤 생산 조건 차이가 결과 차이에 기여했을 가능성이 있는지 해석하되, "
    "단일 비교는 엄밀한 인과 증명이 아니므로 단정적 표현 대신 가능성 서술('~일 가능성이 있습니다' 등)을 사용하세요. "
    "한국어로 작성하세요." + JSON_RESPONSE_INSTRUCTION_KO
)
COMPARE_SYSTEM_PROMPT_EN = (
    "You are an assistant that interprets manufacturing process quality data by comparing two lots. "
    "Do not invent or calculate new numbers — base your interpretation only on the provided "
    "aggregate figures for the two lots. Interpret which production-condition differences may have "
    "contributed to the difference in results, but since a single comparison is not rigorous proof "
    "of causation, use tentative phrasing (e.g. 'may have contributed to') rather than definitive claims. "
    "Write in English." + JSON_RESPONSE_INSTRUCTION_EN
)


def _get_client():
    if OpenAI is None or not config.LLM_BASE_URL or not config.LLM_MODEL:
        return None
    return OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY or "none")


def _parse_structured(content: str, lang: str) -> dict:
    """{"analysis", "recommendation"} 파싱. 실패 시 전체 텍스트를 analysis에 담고
    recommendation=None으로 반환한다 (호출부는 이 경우 기존처럼 단일 문단으로 렌더링)."""
    text = (content or "").strip()
    fenced = text
    if fenced.startswith("```"):
        fenced = fenced.strip("`")
        if fenced.lower().startswith("json"):
            fenced = fenced[4:]
        fenced = fenced.strip()

    try:
        data = json.loads(fenced)
        analysis = str(data.get("analysis", "")).strip()
        recommendation = str(data.get("recommendation", "")).strip()
        if analysis and recommendation:
            return {"analysis": analysis, "recommendation": recommendation}
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    return {"analysis": text if text else FAIL_MESSAGE[lang], "recommendation": None}


def _chat_structured(system_prompt: str, user_payload: dict, lang: str) -> dict:
    """반환: {"analysis": str, "recommendation": str|None}.
    recommendation이 None이면 분리 실패(또는 LLM 미설정/호출 실패) — analysis만 표시."""
    client = _get_client()
    if client is None:
        print("[llm_client] LLM 미설정(LLM_BASE_URL/LLM_MODEL 없음) - 코멘트 생성을 건너뜁니다")
        return {"analysis": FAIL_MESSAGE[lang], "recommendation": None}
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
        return _parse_structured(content, lang)
    except Exception as e:
        print(f"[llm_client] LLM 호출 실패({lang}): {e}")
        return {"analysis": FAIL_MESSAGE[lang], "recommendation": None}


def _chat_bilingual(system_prompt_ko: str, system_prompt_en: str, user_payload: dict) -> dict:
    """한국어/영어 호출을 병렬로 실행해 하나의 이중언어 dict로 합친다.
    반환: {"analysis": {"ko","en"}, "recommendation": {"ko","en"} (둘 다 없으면 빈 값)}."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_ko = ex.submit(_chat_structured, system_prompt_ko, user_payload, "ko")
        fut_en = ex.submit(_chat_structured, system_prompt_en, user_payload, "en")
        result_ko = fut_ko.result()
        result_en = fut_en.result()

    return {
        "analysis": {"ko": result_ko["analysis"], "en": result_en["analysis"]},
        "recommendation": {"ko": result_ko.get("recommendation"), "en": result_en.get("recommendation")},
    }


def generate_lot_comment(agg: dict) -> dict:
    payload = {
        "lot_id": agg["lot_id"],
        "conditions": {
            "temperature": agg["temperature"],
            "head_speed": agg["head_speed"],
        },
        "quantity": agg["quantity"],
        "ok_count": agg["ok_count"],
        "ng_count": agg["ng_count"],
        "defect_rate": agg["defect_rate"],
        "stations": agg["stations"],
    }
    return _chat_bilingual(LOT_SYSTEM_PROMPT_KO, LOT_SYSTEM_PROMPT_EN, payload)


def generate_compare_comment(agg_a: dict, agg_b: dict) -> dict:
    def slim(agg):
        return {
            "lot_id": agg["lot_id"],
            "conditions": {
                "temperature": agg["temperature"],
                "head_speed": agg["head_speed"],
            },
            "quantity": agg["quantity"],
            "ng_count": agg["ng_count"],
            "defect_rate": agg["defect_rate"],
            "stations": agg["stations"],
        }
    payload = {"lot_a": slim(agg_a), "lot_b": slim(agg_b)}
    return _chat_bilingual(COMPARE_SYSTEM_PROMPT_KO, COMPARE_SYSTEM_PROMPT_EN, payload)
