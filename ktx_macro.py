"""
KTX (Korail) 자동 예약 모듈
korail2 라이브러리를 사용합니다.
  pip install korail2
"""

import os
import time
import logging
from dotenv import load_dotenv
from korail2 import Korail, TrainType, ReserveOption, AdultPassenger
from station_resolver import resolve

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
    KTX 자동 예약 실행.

    Returns:
        True  → 예약 성공
        False → 실패
    """
    logger.error(
        "KTX(코레일) API가 현재 자동화 도구를 서버 측에서 차단(MACRO ERROR)하고 있습니다.\n"
        "  → SRT는 정상 작동합니다. 열차 종류를 SRT로 변경해 주세요."
    )
    return False

    korail_id = os.getenv("KORAIL_ID")  # noqa: unreachable
    korail_pw = os.getenv("KORAIL_PW")

    if not korail_id or not korail_pw:
        logger.error(".env 파일에 KORAIL_ID / KORAIL_PW 를 설정하세요.")
        return False

    # ── 역명 자동 매핑 ───────────────────────────────────
    resolved_dep = resolve(departure, "KTX")
    resolved_arr = resolve(destination, "KTX")
    if resolved_dep != departure:
        logger.info(f"출발역 변환: {departure} → {resolved_dep}")
    if resolved_arr != destination:
        logger.info(f"도착역 변환: {destination} → {resolved_arr}")
    departure, destination = resolved_dep, resolved_arr

    # ── 로그인 ────────────────────────────────────────────
    logger.info("Korail 로그인 중...")
    korail = Korail(korail_id, korail_pw)

    # ── 좌석 옵션 매핑 ───────────────────────────────────
    reserve_opt = (
        ReserveOption.GENERAL_ONLY
        if seat_type == "일반실"
        else ReserveOption.SPECIAL_ONLY
    )

    attempt = 0
    while True:
        if _stop_event and _stop_event.is_set():
            logger.info("[KTX] 다른 열차가 먼저 예약됨. 중단.")
            return False

        attempt += 1
        logger.info(f"[KTX 시도 {attempt}] {departure} → {destination} | {date} {time_str}")

        try:
            trains = korail.search_train(
                dep=departure,
                arr=destination,
                date=date,
                time=time_str,
                train_type=TrainType.KTX,
                passengers=[AdultPassenger(adult)],
            )

            if not trains:
                logger.info("검색된 열차가 없습니다.")
            else:
                for train in trains:
                    logger.info(
                        f"  열차: {train.train_name} {train.dep_time}→{train.arr_time} "
                        f"| 일반실: {train.general_seat_state} / 특실: {train.special_seat_state}"
                    )

                # 예약 가능한 열차 선택
                for train in trains:
                    avail = (
                        train.general_seat_state == "예약가능"
                        if seat_type == "일반실"
                        else train.special_seat_state == "예약가능"
                    )
                    if avail:
                        logger.info(f"예약 시도: {train.train_name} {train.dep_time}")
                        reservation = korail.reserve(train, option=reserve_opt)
                        logger.info(f"예약 성공! 예약번호: {reservation.rsv_id}")

                        if auto_payment:
                            _pay_ktx(korail, reservation)

                        return True

                logger.info("현재 예약 가능한 열차 없음. 재시도 대기...")

        except Exception as exc:
            logger.warning(f"오류 발생: {exc}")

        if max_retry and attempt >= max_retry:
            logger.error(f"최대 재시도 횟수({max_retry}) 초과. 종료합니다.")
            return False

        time.sleep(retry_interval)


def _pay_ktx(korail, reservation):
    """카드 자동결제 (korail2 pay API 사용)."""
    try:
        korail.pay_with_card(reservation)
        logger.info("결제 완료!")
    except Exception as exc:
        logger.error(f"결제 실패: {exc}")
