"""
SRT 자동 예약 - 헤드리스 서버 실행용 (GitHub Actions)
환경변수로 설정값을 받아 GUI 없이 동작
"""

import os
import sys
import time
import json
import requests
from datetime import datetime

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "booking_config.json")


def load_file_config() -> dict:
    """booking_config.json 읽기. 없으면 빈 딕셔너리 반환."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

try:
    from SRT import SRT
    from SRT.passenger import Adult
    from SRT.seat_type import SeatType
except ImportError:
    print("SRT 라이브러리가 없습니다.")
    print("pip install git+https://github.com/ryanking13/SRT.git")
    sys.exit(1)


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def send_telegram(token: str, chat_id: str, message: str):
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=10)
    except Exception as e:
        log(f"텔레그램 전송 실패: {e}")


def seat_available(train, seat_type_str: str) -> bool:
    gen = train.general_seat_available()
    spc = train.special_seat_available()
    if seat_type_str == "SPECIAL_ONLY":
        return spc
    elif seat_type_str == "GENERAL_ONLY":
        return gen
    elif seat_type_str == "SPECIAL_FIRST":
        return spc or gen
    else:  # GENERAL_FIRST
        return gen or spc


def main():
    # ── 설정 파일 읽기 (기본값) ────────────────────────────────────────────
    fc = load_file_config()

    # ── 환경변수 우선, 없으면 설정 파일값 사용 ────────────────────────────
    def get(env_key, file_key, default):
        v = os.environ.get(env_key, "").strip()
        return v if v else str(fc.get(file_key, default))

    srt_id        = os.environ.get("SRT_ID", "").strip()
    srt_pw        = os.environ.get("SRT_PW", "").strip()
    dep           = get("DEP_STATION",  "dep_station",  "수서")
    arr           = get("ARR_STATION",  "arr_station",  "부산")
    date          = get("DATE",         "date",         "")
    start_raw     = get("START_TIME",   "start_time",   "00:00").replace(":", "")
    end_raw       = get("END_TIME",     "end_time",     "23:59").replace(":", "")
    start_time    = start_raw.ljust(6, "0")
    end_time      = end_raw[:4] + "59"
    passengers    = int(get("PASSENGERS",   "passengers",   "1"))
    seat_type_str = get("SEAT_TYPE",    "seat_type",    "GENERAL_FIRST")
    interval_sec  = int(get("INTERVAL_SEC", "interval_sec", "5"))
    tg_token      = os.environ.get("TG_TOKEN", "").strip()
    tg_chat_id    = os.environ.get("TG_CHAT_ID", "").strip()
    max_duration  = int(os.environ.get("MAX_DURATION_SEC", str(5 * 3600)))

    # ── 필수값 확인 ────────────────────────────────────────────────────────
    if not srt_id or not srt_pw:
        log("오류: SRT_ID와 SRT_PW Secret이 필요합니다.")
        sys.exit(1)
    if not date:
        log("오류: DATE 입력값이 필요합니다. (예: 20260410)")
        sys.exit(1)

    # ── 좌석 유형 매핑 ─────────────────────────────────────────────────────
    seat_map = {
        "GENERAL_FIRST": SeatType.GENERAL_FIRST,
        "SPECIAL_FIRST": SeatType.SPECIAL_FIRST,
        "GENERAL_ONLY":  SeatType.GENERAL_ONLY,
        "SPECIAL_ONLY":  SeatType.SPECIAL_ONLY,
    }
    seat_type = seat_map.get(seat_type_str, SeatType.GENERAL_FIRST)

    log("=" * 50)
    log("SRT 자동 예약 시작 (GitHub Actions)")
    log(f"구간: {dep} → {arr}")
    log(f"날짜: {date}  시간: {start_time[:2]}:{start_time[2:4]} ~ {end_time[:2]}:{end_time[2:4]}")
    log(f"인원: {passengers}명  좌석: {seat_type_str}  간격: {interval_sec}초")
    log(f"최대 실행: {max_duration // 3600}시간 {(max_duration % 3600) // 60}분")
    log("=" * 50)

    # ── 로그인 ─────────────────────────────────────────────────────────────
    log("로그인 시도 중...")
    try:
        srt = SRT(srt_id, srt_pw)
        log("로그인 성공!")
    except Exception as e:
        log(f"로그인 실패: {e}")
        send_telegram(tg_token, tg_chat_id, f"❌ SRT 로그인 실패\n{e}")
        sys.exit(1)

    # ── 예약 루프 ──────────────────────────────────────────────────────────
    pax = [Adult() for _ in range(passengers)]
    attempt = 0
    start_wall = time.time()

    while True:
        # 최대 실행 시간 체크
        elapsed = time.time() - start_wall
        if elapsed >= max_duration:
            log(f"최대 실행 시간 도달. 종료합니다.")
            send_telegram(tg_token, tg_chat_id,
                f"⏰ SRT 매크로 시간 초과 종료\n{dep}→{arr} {date}\n"
                f"다시 실행해주세요.")
            sys.exit(0)

        attempt += 1
        log(f"[{attempt}회] 검색 중... (경과: {int(elapsed // 60)}분)")

        try:
            trains = srt.search_train(dep, arr, date, start_time, available_only=False)
            trains = [t for t in trains if t.dep_time[:6] <= end_time]

            if not trains:
                log("해당 시간대 열차 없음.")
            else:
                any_avail = False
                for train in trains:
                    dh = train.dep_time[:2]
                    dm = train.dep_time[2:4]
                    gen_ok = train.general_seat_available()
                    spc_ok = train.special_seat_available()
                    log(f"  {train.train_name} {train.train_number}호 {dh}:{dm} "
                        f"[일반{'O' if gen_ok else 'X'} 특{'O' if spc_ok else 'X'}]")

                    if seat_available(train, seat_type_str):
                        any_avail = True
                        log(f"  → 예약 가능 좌석 발견! 예약 시도 중...")
                        try:
                            reservation = srt.reserve(train, passengers=pax, special_seat=seat_type)
                            res_num    = reservation.reservation_number
                            cost       = reservation.total_cost
                            train_info = f"{train.train_name} {train.train_number}호 {dh}:{dm} 출발"
                            log(f"예약 완료! 예약번호: {res_num} | {cost:,}원 | {train_info}")
                            send_telegram(tg_token, tg_chat_id,
                                f"🚅 SRT 예약 완료!\n\n"
                                f"예약번호: {res_num}\n"
                                f"열차: {train_info}\n"
                                f"결제 금액: {cost:,}원")
                            sys.exit(0)
                        except Exception as re:
                            log(f"  → 예약 실패: {re}")

                if not any_avail:
                    log(f"예약 가능 좌석 없음. {interval_sec}초 후 재검색...")

        except Exception as e:
            log(f"검색 오류: {e}")

        time.sleep(interval_sec)


if __name__ == "__main__":
    main()
