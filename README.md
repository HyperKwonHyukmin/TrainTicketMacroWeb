# KTX / SRT 자동 예약 매크로

매진된 열차 티켓을 자동으로 재시도해서 예약해주는 Python 매크로입니다.

## 설치

```bash
pip install -r requirements.txt
```

## 설정

### 1. 계정 정보 (.env)

`.env.example`을 복사해서 `.env`를 만든 후 계정 정보를 입력하세요.

```bash
cp .env.example .env
```

```env
# KTX 계정 (코레일 회원번호 또는 이메일)
KORAIL_ID=your_id
KORAIL_PW=your_password

# SRT 계정 (멤버십 번호 또는 이메일)
SRT_ID=your_id
SRT_PW=your_password
```

### 2. 예약 설정 (config.py)

`config.py`에서 열차 종류, 출발역, 도착역, 날짜 등을 설정합니다.

```python
TRAIN_TYPE  = "SRT"        # "KTX" 또는 "SRT"
DEPARTURE   = "수서"
DESTINATION = "부산"
DATE        = "20260401"   # YYYYMMDD
TIME        = "080000"     # HHMMSS (이 시각 이후 열차 검색)
ADULT_COUNT = 1
SEAT_TYPE   = "일반실"     # "일반실" 또는 "특실"

RETRY_INTERVAL_SEC = 5     # 재시도 간격 (초)
MAX_RETRY          = 0     # 0 = 무한 재시도
AUTO_PAYMENT       = False # True = 예약 즉시 자동 결제
```

## 실행

### 기본 실행 (config.py 설정 사용)

```bash
python main.py
```

### 커맨드라인으로 직접 지정

```bash
# SRT 수서→부산 4월 1일 08시 이후
python main.py --type SRT --dep 수서 --arr 부산 --date 20260401 --time 080000

# KTX 서울→부산 2인 특실
python main.py --type KTX --dep 서울 --arr 부산 --date 20260401 --time 070000 --adult 2 --seat 특실

# 3초마다 재시도, 최대 100번
python main.py --interval 3 --retry 100
```

## 주요 역명

| KTX | SRT |
|-----|-----|
| 서울, 용산, 광명, 수원 | 수서, 동탄, 지제 |
| 천안아산, 오송, 대전 | 천안아산, 오송, 대전 |
| 동대구, 경주, 울산, 부산 | 동대구, 경주, 울산, 부산 |
| 익산, 정읍, 광주송정, 목포 | 익산, 정읍, 광주송정, 목포 |

## 주의사항

- **자동결제(`AUTO_PAYMENT = True`)는 실제 카드 결제가 발생**하므로 주의하세요.
- 기본값은 `AUTO_PAYMENT = False`로 예약만 해두고 수동으로 결제합니다.
- 너무 짧은 재시도 간격(1초 미만)은 서버 차단을 유발할 수 있습니다.
- 로그는 `booking.log` 파일에 저장됩니다.
