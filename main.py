"""
KTX / SRT 자동 예약 매크로
-------------------------------
  python main.py        → 대화형 입력
  python main.py --help → 커맨드라인 옵션 확인
"""

import argparse
import logging
import sys
import threading
from datetime import datetime, date

# ── 로깅 설정 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("booking.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── 대화형 입력 헬퍼 ───────────────────────────────────────

def ask(prompt: str, default: str = "", validator=None) -> str:
    """기본값 표시 + 입력 검증."""
    hint = f" [{default}]" if default else ""
    while True:
        raw = input(f"{prompt}{hint}: ").strip()
        value = raw if raw else default
        if not value:
            print("  값을 입력하세요.")
            continue
        if validator:
            result = validator(value)
            if result is not True:
                print(f"  {result}")
                continue
        return value


def validate_date(v: str):
    """YYYYMMDD 또는 MM/DD 또는 MMDD 형식 허용 → YYYYMMDD 반환."""
    v = v.replace("/", "").replace("-", "")
    today = date.today()
    if len(v) == 4:                          # MMDD
        v = f"{today.year}{v}"
    if len(v) != 8 or not v.isdigit():
        return "날짜는 YYYYMMDD 또는 MMDD 형식으로 입력하세요. (예: 20260401 또는 0401)"
    try:
        datetime.strptime(v, "%Y%m%d")
    except ValueError:
        return "올바른 날짜가 아닙니다."
    return v                                 # 문자열 반환 = 성공


def validate_time(v: str):
    """HH:MM 또는 HHMM 또는 HH 형식 허용 → HHMMSS 반환."""
    v = v.replace(":", "").replace("시", "").strip()
    if len(v) <= 2:
        v = v.zfill(2) + "0000"
    elif len(v) == 4:
        v = v + "00"
    if len(v) != 6 or not v.isdigit():
        return "시각은 HH 또는 HH:MM 형식으로 입력하세요. (예: 08 또는 08:30)"
    h, m = int(v[:2]), int(v[2:4])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return "올바른 시각이 아닙니다."
    return v


def validate_train_type(v: str):
    if v.upper() not in ("KTX", "SRT", "BOTH"):
        return "KTX / SRT / BOTH 중 하나를 입력하세요."
    return True


def validate_seat(v: str):
    if v not in ("일반실", "특실"):
        return "'일반실' 또는 '특실'을 입력하세요."
    return True


def validate_adult(v: str):
    if not v.isdigit() or int(v) < 1:
        return "1 이상의 숫자를 입력하세요."
    return True


# ── 대화형 설정 수집 ───────────────────────────────────────

def prompt_settings() -> dict:
    import config  # 기본값 로드

    print("\n" + "=" * 50)
    print("  KTX / SRT 자동 예약 매크로")
    print("  (Enter = 대괄호 기본값 사용)")
    print("=" * 50 + "\n")

    # 열차 종류
    train_type = ask(
        "열차 종류 (KTX / SRT / BOTH)",
        default=config.TRAIN_TYPE,
        validator=validate_train_type,
    ).upper()

    # 출발역 / 도착역
    dep = ask("출발역", default=config.DEPARTURE)
    arr = ask("도착역", default=config.DESTINATION)

    # 날짜
    raw_date = ask(
        "출발일 (YYYYMMDD 또는 MMDD)",
        default=config.DATE,
        validator=lambda v: validate_date(v) if validate_date(v) != v else True,
    )
    date_str = validate_date(raw_date)       # 정규화된 YYYYMMDD

    # 시작 시각
    raw_time = ask(
        "검색 시작 시각 이후로 예약 (HH 또는 HH:MM)",
        default=config.TIME[:4].lstrip("0") or "0",
        validator=lambda v: validate_time(v) if not isinstance(validate_time(v), str) or validate_time(v) == v else True,
    )
    time_str = validate_time(raw_time)       # 정규화된 HHMMSS

    # 인원
    adult = int(ask("성인 인원", default=str(config.ADULT_COUNT), validator=validate_adult))

    # 좌석 등급
    seat = ask("좌석 등급 (일반실 / 특실)", default=config.SEAT_TYPE, validator=validate_seat)

    # 재시도 간격
    interval = int(ask("매진 시 재시도 간격 (초)", default=str(config.RETRY_INTERVAL_SEC),
                        validator=lambda v: True if v.isdigit() and int(v) >= 1 else "1 이상의 숫자를 입력하세요."))

    # 자동결제
    pay_raw = ask("예약 성공 후 자동결제? (y / n)", default="n",
                  validator=lambda v: True if v.lower() in ("y", "n") else "y 또는 n을 입력하세요.")
    auto_pay = pay_raw.lower() == "y"

    print()
    return dict(
        train_type=train_type,
        departure=dep,
        destination=arr,
        date=date_str,
        time_str=time_str,
        adult=adult,
        seat_type=seat,
        retry_interval=interval,
        max_retry=0,          # 대화형 모드는 무한 재시도
        auto_payment=auto_pay,
    )


# ── 커맨드라인 파싱 ────────────────────────────────────────

def parse_args():
    import config
    parser = argparse.ArgumentParser(
        description="KTX/SRT 자동 예약 매크로",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "예시:\n"
            "  python main.py                           # 대화형 입력\n"
            "  python main.py --type SRT --dep 수서 --arr 부산 --date 0401 --time 08\n"
            "  python main.py --type KTX --dep 서울 --arr 부산 --date 20260401 --time 07:30\n"
        ),
    )
    parser.add_argument("--type",     help="KTX, SRT, 또는 BOTH (둘 다 동시 시도)")
    parser.add_argument("--dep",      help="출발역")
    parser.add_argument("--arr",      help="도착역")
    parser.add_argument("--date",     help="날짜 (YYYYMMDD 또는 MMDD)")
    parser.add_argument("--time",     help="시각 (HH 또는 HH:MM)")
    parser.add_argument("--adult",    type=int, help="성인 인원")
    parser.add_argument("--seat",     help="일반실 또는 특실")
    parser.add_argument("--interval", type=int, default=config.RETRY_INTERVAL_SEC, help="재시도 간격(초)")
    parser.add_argument("--pay",      action="store_true", help="자동 결제 활성화")
    return parser.parse_args()


# ── 메인 ──────────────────────────────────────────────────

def main():
    args = parse_args()

    # 커맨드라인에 핵심 인자가 모두 있으면 바로 실행, 아니면 대화형
    cli_mode = all([args.type, args.dep, args.arr, args.date, args.time])

    if cli_mode:
        import config
        settings = dict(
            train_type=args.type.upper(),
            departure=args.dep,
            destination=args.arr,
            date=validate_date(args.date),
            time_str=validate_time(args.time),
            adult=args.adult or config.ADULT_COUNT,
            seat_type=args.seat or config.SEAT_TYPE,
            retry_interval=args.interval,
            max_retry=0,
            auto_payment=args.pay,
        )
    else:
        settings = prompt_settings()

    d, t = settings['date'], settings['time_str']
    logger.info("=" * 50)
    logger.info("예약 시작")
    logger.info(f"  열차   : {settings['train_type']}")
    logger.info(f"  구간   : {settings['departure']} → {settings['destination']}")
    logger.info(f"  일시   : {d[:4]}-{d[4:6]}-{d[6:]} {t[:2]}:{t[2:4]} 이후")
    logger.info(f"  좌석   : {settings['seat_type']} / 성인 {settings['adult']}명")
    logger.info(f"  자동결제: {'ON' if settings['auto_payment'] else 'OFF'}")
    logger.info("=" * 50)

    kwargs = {k: v for k, v in settings.items() if k != "train_type"}
    success = run_booking(settings["train_type"], kwargs)

    if success:
        logger.info("예약이 완료되었습니다!")
    else:
        logger.error("예약에 실패했습니다.")
        sys.exit(1)


def run_booking(train_type: str, kwargs: dict,
                ktx_kwargs: dict = None, srt_kwargs: dict = None,
                stop_event=None) -> bool:
    """
    단일 또는 BOTH 모드 예약 실행.
    - train_type == "KTX"/"SRT": kwargs 사용
    - train_type == "BOTH": ktx_kwargs / srt_kwargs 사용 (없으면 kwargs 공유)
    kwargs에 _stop_event 포함 가능.
    """
    if train_type == "KTX":
        import ktx_macro
        return ktx_macro.run(**kwargs)

    if train_type == "SRT":
        import srt_macro
        return srt_macro.run(**kwargs)

    # ── BOTH: KTX / SRT 동시 시도 ────────────────────────
    import ktx_macro, srt_macro

    outer_stop = stop_event or kwargs.pop("_stop_event", None)
    stop_event = threading.Event()

    # 각 열차별 kwargs 결정 (개별 지정 없으면 공통 kwargs 사용)
    kw_ktx = dict(ktx_kwargs or kwargs)
    kw_srt = dict(srt_kwargs or kwargs)
    kw_ktx.pop("_stop_event", None)
    kw_srt.pop("_stop_event", None)

    def _check_outer():
        if outer_stop:
            while not stop_event.is_set():
                if outer_stop.is_set():
                    stop_event.set()
                    break
                threading.Event().wait(0.3)

    threading.Thread(target=_check_outer, daemon=True).start()

    result = {"success": False}

    def _run(macro, label, kw):
        try:
            ok = macro.run(**kw, _stop_event=stop_event)
            if ok and not result["success"]:
                result["success"] = True
                result["winner"] = label
                stop_event.set()
        except Exception as exc:
            logger.warning(f"[{label}] 오류: {exc}")

    threads = [
        threading.Thread(target=_run, args=(ktx_macro, "KTX", kw_ktx), daemon=True),
        threading.Thread(target=_run, args=(srt_macro, "SRT", kw_srt), daemon=True),
    ]
    logger.info(f"KTX ({kw_ktx['departure']}→{kw_ktx['destination']}) / "
                f"SRT ({kw_srt['departure']}→{kw_srt['destination']}) 동시 검색 시작")
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    if result.get("success"):
        logger.info(f"[{result['winner']}] 예약 성공!")
    return result.get("success", False)


if __name__ == "__main__":
    main()
