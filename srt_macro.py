"""
SRT 자동 예약 모듈
SRT 라이브러리를 사용합니다.
  pip install SRT
"""

import os
import time
import logging
import urllib3
import requests
from dotenv import load_dotenv
from SRT import SRT
from SRT.passenger import Adult
from SRT.seat_type import SeatType
from station_resolver import resolve

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_orig_request = requests.Session.request

def _no_verify(self, method, url, **kwargs):
    kwargs.setdefault("verify", False)
    return _orig_request(self, method, url, **kwargs)

requests.Session.request = _no_verify

load_dotenv()
logger = logging.getLogger(__name__)


def run(
    departure: str,
    destination: str,
    date: str,
    time_str: str,
    adult: int = 1,
    seat_type: str = "일반실",
    retry_interval: int = 5,
    max_retry: int = 0,
    auto_payment: bool = False,
    _stop_event=None,
) -> bool:
    """
    SRT 자동 예약 실행.

    Returns:
        True  → 예약 성공
        False → 실패
    """
    srt_id = os.getenv("SRT_ID")
    srt_pw = os.getenv("SRT_PW")

    if not srt_id or not srt_pw:
        logger.error(".env 파일에 SRT_ID / SRT_PW 를 설정하세요.")
        return False

    # ── 역명 자동 매핑 ───────────────────────────────────
    resolved_dep = resolve(departure, "SRT")
    resolved_arr = resolve(destination, "SRT")
    if resolved_dep != departure:
        logger.info(f"출발역 변환: {departure} → {resolved_dep}")
    if resolved_arr != destination:
        logger.info(f"도착역 변환: {destination} → {resolved_arr}")
    departure, destination = resolved_dep, resolved_arr

    # ── 로그인 ────────────────────────────────────────────
    logger.info("SRT 로그인 중...")
    srt = SRT(srt_id, srt_pw)

    # ── 좌석 타입 매핑 ───────────────────────────────────
    seat_t = (
        SeatType.GENERAL_ONLY
        if seat_type == "일반실"
        else SeatType.SPECIAL_ONLY
    )

    passengers = [Adult()] * adult

    attempt = 0
    while True:
        if _stop_event and _stop_event.is_set():
            logger.info("[SRT] 다른 열차가 먼저 예약됨. 중단.")
            return False

        attempt += 1
        logger.info(f"[SRT 시도 {attempt}] {departure} → {destination} | {date} {time_str[:2]}:{time_str[2:4]}")

        try:
            trains = srt.search_train(
                dep=departure,
                arr=destination,
                date=date,
                time=time_str,
                available_only=False,
            )

            if not trains:
                logger.info("검색된 열차가 없습니다.")
            else:
                for train in trains:
                    logger.info(
                        f"  {train.train_name} {train.dep_time}→{train.arr_time} "
                        f"| 특실: {train.special_seat_state} / 일반: {train.general_seat_state}"
                    )

                # 예약 가능한 열차 선택
                for train in trains:
                    avail = (
                        train.general_seat_available()
                        if seat_type == "일반실"
                        else train.special_seat_available()
                    )
                    if avail:
                        logger.info(f"예약 시도: {train.train_name} {train.dep_time}")
                        reservation = srt.reserve(
                            train,
                            passengers=passengers,
                            special_seat=seat_t,
                        )
                        logger.info(
                            f"예약 성공! 예약번호: {reservation.reservation_number}"
                        )

                        if auto_payment:
                            _pay_srt(srt, reservation)

                        return True

                logger.info("현재 예약 가능한 열차 없음. 재시도 대기...")

        except Exception as exc:
            logger.warning(f"오류 발생: {exc}")

        if max_retry and attempt >= max_retry:
            logger.error(f"최대 재시도 횟수({max_retry}) 초과. 종료합니다.")
            return False

        time.sleep(retry_interval)


def _pay_srt(srt, reservation):
    """카드 자동결제."""
    try:
        srt.pay_with_card(reservation)
        logger.info("결제 완료!")
    except Exception as exc:
        logger.error(f"결제 실패: {exc}")
