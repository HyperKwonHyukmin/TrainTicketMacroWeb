"""
역명 자동 매핑 모듈
- 입력값이 공식 역명에 포함되면 자동으로 정식 역명으로 변환
- 예: "울산" → "울산(통도사)",  "김천" → "김천(구미)"
"""

# ── SRT 공식 역명 (SRT.constants.STATION_CODE 기준) ───────
SRT_STATIONS = [
    "수서", "동탄", "평택지제",
    "천안아산", "오송", "대전", "서대구", "동대구",
    "신경주", "경주", "울산(통도사)", "부산",
    "공주", "익산", "정읍", "광주송정", "나주", "목포",
    "전주", "남원", "곡성", "구례구", "순천", "여천", "여수EXPO",
    "진영", "창원중앙", "창원", "마산", "진주",
    "밀양", "포항",
]

# ── KTX 공식 역명 ─────────────────────────────────────────
KTX_STATIONS = [
    "서울", "용산", "영등포", "광명", "수원", "평택",
    "천안아산", "오송", "대전", "김천(구미)", "동대구",
    "경주", "울산", "부산", "신경주",
    "익산", "정읍", "광주송정", "나주", "목포",
    "전주", "남원", "순천", "여수EXPO",
    "진영", "창원중앙", "창원", "마산",
    "청량리", "상봉", "양평", "원주", "횡성", "둔내",
    "평창", "진부", "강릉",
    "포항", "태화강",
]


def resolve(name: str, train_type: str) -> str:
    """
    입력 역명을 정식 역명으로 변환.
    - 정확히 일치하면 그대로 반환
    - 입력값이 정식 역명에 포함되면 정식 역명 반환
    - 매칭 불가 시 원본 반환 (API에서 오류 처리)

    Args:
        name: 사용자 입력 역명 (예: "울산", "김천")
        train_type: "SRT" 또는 "KTX"

    Returns:
        정식 역명 문자열
    """
    stations = SRT_STATIONS if train_type.upper() == "SRT" else KTX_STATIONS

    # 1. 완전 일치
    if name in stations:
        return name

    # 2. 부분 일치 (입력값이 정식 역명에 포함)
    matches = [s for s in stations if name in s]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # 여러 개 매칭 시 가장 짧은 것(가장 단순한 역명) 우선
        best = min(matches, key=len)
        return best

    # 3. 역방향 부분 일치 (정식 역명이 입력값에 포함)
    matches_rev = [s for s in stations if s in name]
    if matches_rev:
        return min(matches_rev, key=len)

    # 4. 매칭 실패 → 원본 그대로 (API에서 오류 처리)
    return name
