"""공정 측정값 생성 및 판정 로직. 생산 조건(온도·헤드 속도)이 분포에 반영된다."""
import random

import config


def generate_measurement(station: str, temperature: int, head_speed: str):
    """단일 체결 이벤트의 측정값과 판정을 생성한다.

    반환: (value, judgment, lsl, usl, item_name)
    """
    spec = config.STATIONS[station]
    std_factor = config.HEAD_SPEED_PRESETS[head_speed]["std_factor"]
    bias = config.temp_bias(temperature)

    value = round(random.gauss(spec["mean"], spec["std"] * std_factor) + bias, 2)
    judgment = "OK" if spec["lsl"] <= value <= spec["usl"] else "NG"

    return value, judgment, spec["lsl"], spec["usl"], spec["name"]
