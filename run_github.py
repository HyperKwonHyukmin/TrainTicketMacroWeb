"""
GitHub Actions 전용 실행 스크립트.
환경 변수에서 예매 파라미터를 읽어 srt_macro.run()을 호출합니다.
"""

import os
import sys
import logging

# ── 로깅 설정 (GitHub Actions 콘솔에 실시간 출력) ──────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

import srt_macro

# ── 환경 변수에서 파라미터 읽기 ─────────────────────────────────────────────
departure     = os.environ["DEPARTURE"]
destination   = os.environ["DESTINATION"]
date          = os.environ["DATE"]
time_str      = os.environ["TIME"]
adult         = int(os.environ.get("ADULT", "1"))
seat_type     = os.environ.get("SEAT_TYPE", "일반실")
retry_interval = int(os.environ.get("RETRY_INTERVAL", "5"))
max_retry     = int(os.environ.get("MAX_RETRY", "0"))

logging.info("=" * 50)
logging.info("SRT 자동 예매 시작")
logging.info(f"  노선     : {departure} → {destination}")
logging.info(f"  날짜     : {date}")
logging.info(f"  최소시간 : {time_str[:2]}:{time_str[2:4]}")
logging.info(f"  인원     : 성인 {adult}명")
logging.info(f"  좌석     : {seat_type}")
logging.info(f"  재시도   : {retry_interval}초 간격" + (f", 최대 {max_retry}회" if max_retry else ", 무제한"))
logging.info("=" * 50)

success = srt_macro.run(
    departure=departure,
    destination=destination,
    date=date,
    time_str=time_str,
    adult=adult,
    seat_type=seat_type,
    retry_interval=retry_interval,
    max_retry=max_retry,
    auto_payment=False,  # 자동결제 항상 비활성화 (안전)
)

if success:
    logging.info("✅ 예매 성공! SRT 앱/사이트에서 결제를 완료하세요.")
    sys.exit(0)
else:
    logging.error("❌ 예매 실패 또는 최대 재시도 초과.")
    sys.exit(1)
