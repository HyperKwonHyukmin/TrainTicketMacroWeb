"""
SRT 자동 예약 프로그램
- 출발역, 도착역, 날짜, 시작/종료 시간을 설정하면 해당 시간대 기차를 반복 검색하여 자동 예약
- pip install SRT 필요
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import queue
import time
import json
import os
import requests
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "srt_config.json")

# ─── SRT 라이브러리 임포트 ────────────────────────────────────────────────────
try:
    from SRT import SRT
    from SRT.passenger import Adult
    from SRT.seat_type import SeatType
    SRT_AVAILABLE = True
except ImportError:
    SRT_AVAILABLE = False

# ─── 상수 ────────────────────────────────────────────────────────────────────
STATIONS = [
    "수서", "동탄", "평택지제", "천안아산", "오송", "대전", "김천구미",
    "동대구", "신경주", "울산(통도사)", "부산", "마산", "창원중앙",
    "광주송정", "목포", "익산", "전주", "남원", "곡성", "구례구",
    "순천", "여수EXPO", "여천", "진주", "포항",
]

SEAT_TYPES = {
    "일반실 우선": "GENERAL_FIRST",
    "특실 우선":   "SPECIAL_FIRST",
    "일반실만":    "GENERAL_ONLY",
    "특실만":      "SPECIAL_ONLY",
}

LOG_COLORS = {
    "INFO":    "black",
    "SUCCESS": "#007700",
    "WARNING": "#cc6600",
    "ERROR":   "#cc0000",
}


# ─── 데이터 모델 ──────────────────────────────────────────────────────────────
@dataclass
class BookingConfig:
    srt_id: str
    srt_pw: str
    dep_station: str
    arr_station: str
    date: str           # YYYYMMDD
    start_time: str     # HHMMSS
    end_time: str       # HHMMSS
    passengers: int
    seat_type: str      # GENERAL_FIRST / SPECIAL_FIRST / GENERAL_ONLY / SPECIAL_ONLY
    interval_sec: int
    tg_token: str = ""  # Telegram Bot 토큰
    tg_chat_id: str = ""  # Telegram Chat ID


@dataclass
class LogMessage:
    level: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class BookingResult:
    success: bool
    reservation_number: Optional[str] = None
    total_cost: Optional[int] = None
    train_info: Optional[str] = None
    error: Optional[str] = None


# ─── Telegram 알림 ───────────────────────────────────────────────────────────
def send_telegram(token: str, chat_id: str, message: str) -> tuple:
    """텔레그램 메시지 전송. (성공여부, 오류메시지) 반환."""
    if not token or not chat_id:
        return False, "토큰 또는 Chat ID가 비어있습니다."
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return True, ""
        return False, data.get("description", "알 수 없는 오류")
    except Exception as e:
        return False, str(e)


# ─── SRT 클라이언트 래퍼 ──────────────────────────────────────────────────────
class SRTClient:
    def __init__(self):
        self._srt: Optional[SRT] = None

    def login(self, srt_id: str, srt_pw: str) -> None:
        """로그인. 실패 시 예외 발생."""
        self._srt = SRT(srt_id, srt_pw)

    def search_trains(self, config: BookingConfig) -> list:
        """시간 범위 내 열차 검색 (전체 좌석 상태 포함)."""
        trains = self._srt.search_train(
            config.dep_station,
            config.arr_station,
            config.date,
            config.start_time,
            available_only=False,
        )
        # end_time 이하인 열차만 반환
        return [t for t in trains if t.dep_time[:6] <= config.end_time]

    def reserve(self, train, config: BookingConfig):
        """예약 시도. 성공 시 reservation 반환."""
        passengers = [Adult() for _ in range(config.passengers)]

        if config.seat_type == "SPECIAL_FIRST":
            special = SeatType.SPECIAL_FIRST
        elif config.seat_type == "SPECIAL_ONLY":
            special = SeatType.SPECIAL_ONLY
        elif config.seat_type == "GENERAL_ONLY":
            special = SeatType.GENERAL_ONLY
        else:
            special = SeatType.GENERAL_FIRST

        return self._srt.reserve(train, passengers=passengers, special_seat=special)

    def seat_available(self, train, seat_type: str) -> bool:
        """좌석 유형에 따라 예약 가능 여부 확인."""
        if seat_type == "SPECIAL_ONLY":
            return train.special_seat_available()
        elif seat_type == "GENERAL_ONLY":
            return train.general_seat_available()
        elif seat_type == "SPECIAL_FIRST":
            return train.special_seat_available() or train.general_seat_available()
        else:  # GENERAL_FIRST
            return train.general_seat_available() or train.special_seat_available()


# ─── 백그라운드 워커 ──────────────────────────────────────────────────────────
class BookingWorker(threading.Thread):
    def __init__(self, config: BookingConfig, client: SRTClient, msg_queue: queue.Queue):
        super().__init__(daemon=True)
        self.config = config
        self.client = client
        self.queue = msg_queue
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _put(self, level: str, text: str):
        self.queue.put(LogMessage(level=level, text=text))

    def run(self):
        config = self.config
        client = self.client

        # 로그인
        self._put("INFO", f"로그인 시도 중... (ID: {config.srt_id})")
        try:
            client.login(config.srt_id, config.srt_pw)
            self._put("SUCCESS", "로그인 성공!")
        except Exception as e:
            self._put("ERROR", f"로그인 실패: {e}")
            self.queue.put(BookingResult(success=False, error=str(e)))
            return

        attempt = 0
        start_disp = f"{config.start_time[:2]}:{config.start_time[2:4]}"
        end_disp   = f"{config.end_time[:2]}:{config.end_time[2:4]}"

        while not self._stop_event.is_set():
            attempt += 1
            self._put("INFO",
                f"[{attempt}회] {config.dep_station} → {config.arr_station} "
                f"({config.date} {start_disp}~{end_disp}) 검색 중...")

            try:
                trains = client.search_trains(config)

                if not trains:
                    self._put("WARNING", "해당 시간대 열차가 없습니다.")
                else:
                    found = False
                    for train in trains:
                        dep_h = train.dep_time[:2]
                        dep_m = train.dep_time[2:4]
                        gen_ok = train.general_seat_available()
                        spc_ok = train.special_seat_available()
                        avail_str = " | ".join(filter(None, [
                            "일반실 O" if gen_ok else "일반실 X",
                            "특실 O"   if spc_ok else "특실 X",
                        ]))
                        self._put("INFO",
                            f"  {train.train_name} {train.train_number}호 "
                            f"{dep_h}:{dep_m} 출발  [{avail_str}]")

                        if client.seat_available(train, config.seat_type):
                            self._put("INFO", "  → 예약 가능 좌석 발견! 예약 시도 중...")
                            try:
                                reservation = client.reserve(train, config)
                                res_num  = reservation.reservation_number
                                cost     = reservation.total_cost
                                train_info = (
                                    f"{train.train_name} {train.train_number}호 "
                                    f"{dep_h}:{dep_m} 출발"
                                )
                                self._put("SUCCESS",
                                    f"예약 완료! 예약번호: {res_num}  |  "
                                    f"결제 금액: {cost:,}원  |  {train_info}")
                                # 텔레그램 알림
                                if config.tg_token and config.tg_chat_id:
                                    tg_msg = (
                                        f"🚅 SRT 예약 완료!\n\n"
                                        f"예약번호: {res_num}\n"
                                        f"열차: {train_info}\n"
                                        f"결제 금액: {cost:,}원"
                                    )
                                    ok, err = send_telegram(config.tg_token, config.tg_chat_id, tg_msg)
                                    self._put("INFO", f"텔레그램 알림 {'전송 완료' if ok else f'전송 실패: {err}'}")
                                self.queue.put(BookingResult(
                                    success=True,
                                    reservation_number=res_num,
                                    total_cost=cost,
                                    train_info=train_info,
                                ))
                                return
                            except Exception as re:
                                self._put("ERROR", f"  → 예약 실패: {re}")
                        # 첫 번째 가능 열차만 시도하고 싶으면 found=True; break 추가 가능
                    else:
                        if not any(client.seat_available(t, config.seat_type) for t in trains):
                            self._put("WARNING",
                                f"현재 예약 가능 좌석 없음. "
                                f"{config.interval_sec}초 후 재검색...")

            except Exception as e:
                self._put("ERROR", f"검색 오류: {e}")

            self._stop_event.wait(timeout=config.interval_sec)

        self._put("INFO", "검색이 중지되었습니다.")


# ─── GUI 메인 앱 ──────────────────────────────────────────────────────────────
class SRTBookingApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("SRT 자동 예약 프로그램")
        self.root.geometry("640x870")
        self.root.resizable(False, False)

        self._queue: queue.Queue = queue.Queue()
        self._worker: Optional[BookingWorker] = None
        self._client = SRTClient()

        self._build_ui()
        self._load_config()
        self._poll_queue()

        if not SRT_AVAILABLE:
            messagebox.showwarning(
                "라이브러리 없음",
                "SRT 라이브러리가 설치되어 있지 않습니다.\n\n"
                "터미널에서 다음 명령어를 실행해주세요:\n"
                "  pip install SRT",
            )

    # ── UI 구성 ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 타이틀
        ttk.Label(main, text="SRT 자동 예약 프로그램",
                  font=("맑은 고딕", 15, "bold")).pack(**pad)

        # ── 로그인 ────────────────────────────────────────────────────────────
        lf = ttk.LabelFrame(main, text="로그인 정보", padding=8)
        lf.pack(fill=tk.X, **pad)

        self.id_var = self._labeled_entry(lf, "아이디 (전화번호/이메일):", 0, width=28)
        self.pw_var = self._labeled_entry(lf, "비밀번호:", 1, width=28, show="*")

        # ── 검색 조건 ─────────────────────────────────────────────────────────
        sf = ttk.LabelFrame(main, text="검색 조건", padding=8)
        sf.pack(fill=tk.X, **pad)

        # 출발/도착역
        r0 = ttk.Frame(sf); r0.grid(row=0, column=0, sticky="w", pady=3)
        ttk.Label(r0, text="출발역:", width=14).pack(side=tk.LEFT)
        self.dep_var = tk.StringVar(value="수서")
        ttk.Combobox(r0, textvariable=self.dep_var, values=STATIONS, width=12,
                     state="readonly").pack(side=tk.LEFT)
        ttk.Label(r0, text="  도착역:", width=8).pack(side=tk.LEFT)
        self.arr_var = tk.StringVar(value="부산")
        ttk.Combobox(r0, textvariable=self.arr_var, values=STATIONS, width=12,
                     state="readonly").pack(side=tk.LEFT)

        # 날짜
        r1 = ttk.Frame(sf); r1.grid(row=1, column=0, sticky="w", pady=3)
        ttk.Label(r1, text="날짜 (YYYYMMDD):", width=18).pack(side=tk.LEFT)
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y%m%d"))
        ttk.Entry(r1, textvariable=self.date_var, width=12).pack(side=tk.LEFT)

        # 시작/종료 시간
        r2 = ttk.Frame(sf); r2.grid(row=2, column=0, sticky="w", pady=3)
        ttk.Label(r2, text="시작 시간 (HH:MM):", width=18).pack(side=tk.LEFT)
        self.start_h = tk.StringVar(value="00")
        self.start_m = tk.StringVar(value="00")
        ttk.Spinbox(r2, from_=0, to=23, textvariable=self.start_h,
                    width=4, format="%02.0f").pack(side=tk.LEFT)
        ttk.Label(r2, text=":").pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=0, to=59, textvariable=self.start_m,
                    width=4, format="%02.0f").pack(side=tk.LEFT)

        ttk.Label(r2, text="   종료 시간 (HH:MM):", width=20).pack(side=tk.LEFT)
        self.end_h = tk.StringVar(value="23")
        self.end_m = tk.StringVar(value="59")
        ttk.Spinbox(r2, from_=0, to=23, textvariable=self.end_h,
                    width=4, format="%02.0f").pack(side=tk.LEFT)
        ttk.Label(r2, text=":").pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=0, to=59, textvariable=self.end_m,
                    width=4, format="%02.0f").pack(side=tk.LEFT)

        # 인원/좌석
        r3 = ttk.Frame(sf); r3.grid(row=3, column=0, sticky="w", pady=3)
        ttk.Label(r3, text="인원 수:", width=10).pack(side=tk.LEFT)
        self.pax_var = tk.StringVar(value="1")
        ttk.Spinbox(r3, from_=1, to=9, textvariable=self.pax_var, width=4).pack(side=tk.LEFT)
        ttk.Label(r3, text="   좌석 유형:", width=12).pack(side=tk.LEFT)
        self.seat_var = tk.StringVar(value="일반실 우선")
        ttk.Combobox(r3, textvariable=self.seat_var, values=list(SEAT_TYPES.keys()),
                     width=12, state="readonly").pack(side=tk.LEFT)

        # ── 옵션 ──────────────────────────────────────────────────────────────
        of = ttk.LabelFrame(main, text="옵션", padding=8)
        of.pack(fill=tk.X, **pad)

        r4 = ttk.Frame(of); r4.pack(fill=tk.X, pady=2)
        ttk.Label(r4, text="검색 간격 (초):", width=14).pack(side=tk.LEFT)
        self.interval_var = tk.StringVar(value="5")
        ttk.Spinbox(r4, from_=1, to=60, textvariable=self.interval_var,
                    width=5).pack(side=tk.LEFT)
        ttk.Label(r4, text="   ※ 최소 1초 (서버 부하 주의)").pack(side=tk.LEFT)

        self.alert_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(of, text="예약 성공 시 팝업 알림", variable=self.alert_var).pack(anchor=tk.W)

        # ── 텔레그램 알림 ──────────────────────────────────────────────────────
        tf = ttk.LabelFrame(main, text="텔레그램 알림 (선택)", padding=8)
        tf.pack(fill=tk.X, **pad)

        t0 = ttk.Frame(tf); t0.pack(fill=tk.X, pady=2)
        ttk.Label(t0, text="Bot 토큰:", width=12).pack(side=tk.LEFT)
        self.tg_token_var = tk.StringVar()
        ttk.Entry(t0, textvariable=self.tg_token_var, width=38, show="*").pack(side=tk.LEFT, padx=4)

        t1 = ttk.Frame(tf); t1.pack(fill=tk.X, pady=2)
        ttk.Label(t1, text="Chat ID:", width=12).pack(side=tk.LEFT)
        self.tg_chat_var = tk.StringVar()
        ttk.Entry(t1, textvariable=self.tg_chat_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(t1, text="테스트 전송", command=self._test_telegram, width=12).pack(side=tk.LEFT, padx=4)

        ttk.Label(tf, text="※ @BotFather에서 토큰 발급 → 봇에게 메시지 → /getUpdates로 Chat ID 확인",
                  foreground="gray", font=("맑은 고딕", 8)).pack(anchor=tk.W)

        # ── 버튼 ──────────────────────────────────────────────────────────────
        bf = ttk.Frame(main); bf.pack(fill=tk.X, padx=10, pady=4)
        self.start_btn = ttk.Button(bf, text="▶  예매 시작", command=self.start_booking,
                                    width=16)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn  = ttk.Button(bf, text="■  중 지", command=self.stop_booking,
                                    width=16, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="로그 지우기", command=self.clear_log,
                   width=12).pack(side=tk.LEFT, padx=4)

        # 상태 표시
        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(main, textvariable=self.status_var,
                  font=("맑은 고딕", 10, "bold"), foreground="#0055cc").pack()

        # ── 로그 ──────────────────────────────────────────────────────────────
        logf = ttk.LabelFrame(main, text="로그", padding=5)
        logf.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(
            logf, height=12, state=tk.DISABLED,
            font=("Consolas", 9), wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        for level, color in LOG_COLORS.items():
            self.log_text.tag_configure(level, foreground=color)

    def _labeled_entry(self, parent, label, row, width=20, show=None):
        f = ttk.Frame(parent)
        f.grid(row=row, column=0, sticky="w", pady=3)
        ttk.Label(f, text=label, width=24).pack(side=tk.LEFT)
        var = tk.StringVar()
        kw = {"textvariable": var, "width": width}
        if show:
            kw["show"] = show
        ttk.Entry(f, **kw).pack(side=tk.LEFT)
        return var

    # ── 입력 유효성 검사 ───────────────────────────────────────────────────────
    def _validate(self) -> Optional[BookingConfig]:
        errors = []

        srt_id = self.id_var.get().strip()
        srt_pw = self.pw_var.get().strip()
        if not srt_id: errors.append("아이디를 입력해주세요.")
        if not srt_pw: errors.append("비밀번호를 입력해주세요.")

        dep = self.dep_var.get()
        arr = self.arr_var.get()
        if dep == arr:
            errors.append("출발역과 도착역이 같습니다.")

        date = self.date_var.get().strip()
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError:
            errors.append("날짜 형식이 올바르지 않습니다. (예: 20260407)")

        try:
            sh = int(self.start_h.get()); sm = int(self.start_m.get())
            eh = int(self.end_h.get());   em = int(self.end_m.get())
            start_time = f"{sh:02d}{sm:02d}00"
            end_time   = f"{eh:02d}{em:02d}59"
            if start_time >= end_time:
                errors.append("시작 시간이 종료 시간보다 같거나 늦습니다.")
        except ValueError:
            errors.append("시간 값이 올바르지 않습니다.")
            start_time = end_time = "000000"

        if not SRT_AVAILABLE:
            errors.append("SRT 라이브러리가 설치되지 않았습니다. (pip install SRT)")

        if errors:
            messagebox.showerror("입력 오류", "\n".join(errors))
            return None

        return BookingConfig(
            srt_id=srt_id,
            srt_pw=srt_pw,
            dep_station=dep,
            arr_station=arr,
            date=date,
            start_time=start_time,
            end_time=end_time,
            passengers=int(self.pax_var.get()),
            seat_type=SEAT_TYPES[self.seat_var.get()],
            interval_sec=max(1, int(self.interval_var.get())),
            tg_token=self.tg_token_var.get().strip(),
            tg_chat_id=self.tg_chat_var.get().strip(),
        )

    # ── 설정 저장/불러오기 ─────────────────────────────────────────────────────
    def _save_config(self):
        data = {
            "srt_id":      self.id_var.get(),
            "srt_pw":      self.pw_var.get(),
            "dep_station": self.dep_var.get(),
            "arr_station": self.arr_var.get(),
            "date":        self.date_var.get(),
            "start_h":     self.start_h.get(),
            "start_m":     self.start_m.get(),
            "end_h":       self.end_h.get(),
            "end_m":       self.end_m.get(),
            "passengers":  self.pax_var.get(),
            "seat_type":   self.seat_var.get(),
            "interval":    self.interval_var.get(),
            "alert":       self.alert_var.get(),
            "tg_token":    self.tg_token_var.get(),
            "tg_chat_id":  self.tg_chat_var.get(),
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.id_var.set(data.get("srt_id", ""))
            self.pw_var.set(data.get("srt_pw", ""))
            self.dep_var.set(data.get("dep_station", "수서"))
            self.arr_var.set(data.get("arr_station", "부산"))
            self.date_var.set(data.get("date", datetime.now().strftime("%Y%m%d")))
            self.start_h.set(data.get("start_h", "00"))
            self.start_m.set(data.get("start_m", "00"))
            self.end_h.set(data.get("end_h", "23"))
            self.end_m.set(data.get("end_m", "59"))
            self.pax_var.set(data.get("passengers", "1"))
            self.seat_var.set(data.get("seat_type", "일반실 우선"))
            self.interval_var.set(data.get("interval", "5"))
            self.alert_var.set(data.get("alert", True))
            self.tg_token_var.set(data.get("tg_token", ""))
            self.tg_chat_var.set(data.get("tg_chat_id", ""))
        except Exception:
            pass  # 설정 파일 오류 시 기본값 유지

    # ── 텔레그램 테스트 ────────────────────────────────────────────────────────
    def _test_telegram(self):
        token   = self.tg_token_var.get().strip()
        chat_id = self.tg_chat_var.get().strip()
        if not token or not chat_id:
            messagebox.showwarning("텔레그램", "Bot 토큰과 Chat ID를 모두 입력해주세요.")
            return
        ok, err = send_telegram(token, chat_id, "✅ SRT 예약 프로그램 텔레그램 연결 테스트 성공!")
        if ok:
            messagebox.showinfo("텔레그램", "테스트 메시지 전송 성공!")
        else:
            messagebox.showerror("텔레그램", f"전송 실패:\n{err}")

    # ── 예약 시작/중지 ─────────────────────────────────────────────────────────
    def start_booking(self):
        config = self._validate()
        if config is None:
            return

        self._save_config()
        self._client = SRTClient()
        self._worker = BookingWorker(config, self._client, self._queue)
        self._worker.start()

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("검색 중...")

    def stop_booking(self):
        if self._worker and self._worker.is_alive():
            self._worker.stop()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("중지됨")

    # ── 큐 폴링 ────────────────────────────────────────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, LogMessage):
                    self._append_log(item)
                elif isinstance(item, BookingResult):
                    self._on_booking_result(item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_booking_result(self, result: BookingResult):
        if result.success:
            self.status_var.set("예약 완료!")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            if self.alert_var.get():
                self.root.bell()
                messagebox.showinfo(
                    "예약 성공",
                    f"예약이 완료되었습니다!\n\n"
                    f"예약번호: {result.reservation_number}\n"
                    f"열차 정보: {result.train_info}\n"
                    f"결제 금액: {result.total_cost:,}원",
                )
        else:
            self.status_var.set("오류 발생")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    # ── 로그 출력 ──────────────────────────────────────────────────────────────
    def _append_log(self, msg: LogMessage):
        ts = msg.timestamp.strftime("%H:%M:%S")
        line = f"[{ts}] {msg.text}\n"
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line, msg.level)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)


# ─── 진입점 ──────────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()
    SRTBookingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
