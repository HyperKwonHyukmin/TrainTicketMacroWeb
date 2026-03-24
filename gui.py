"""
KTX / SRT 자동 예약 매크로 - GUI
  python gui.py
"""

import threading
import logging
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import date as dt_date

# ── 로그 핸들러 ───────────────────────────────────────────
class TextHandler(logging.Handler):
    def __init__(self, widget: scrolledtext.ScrolledText):
        super().__init__()
        self.widget = widget
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, record):
        msg = self.format(record)
        level = record.levelname
        def append():
            self.widget.configure(state="normal")
            self.widget.insert(tk.END, msg + "\n", level)
            self.widget.see(tk.END)
            self.widget.configure(state="disabled")
        self.widget.after(0, append)


# ── 메인 앱 ───────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("KTX / SRT 자동 예약 매크로")
        self.resizable(False, False)
        self._stop_event = None
        self._thread = None
        self._build_ui()
        self._setup_logging()

    def _build_ui(self):
        PAD = dict(padx=10, pady=4)

        # ── 열차 종류 ─────────────────────────────────────
        top = ttk.LabelFrame(self, text="예약 설정", padding=10)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        ttk.Label(top, text="열차 종류").grid(row=0, column=0, sticky="w", **PAD)
        self.var_type = tk.StringVar(value="SRT")
        type_frm = ttk.Frame(top)
        type_frm.grid(row=0, column=1, columnspan=3, sticky="w")
        for val in ("KTX", "SRT", "BOTH"):
            ttk.Radiobutton(type_frm, text=val, variable=self.var_type,
                            value=val, command=self._on_type_change).pack(side="left", padx=6)

        self.lbl_ktx_warn = ttk.Label(
            type_frm,
            text="⚠ KTX는 현재 API 차단으로 사용 불가 (SRT 권장)",
            foreground="#f0a000",
        )
        self.lbl_ktx_warn.pack(side="left", padx=10)
        self.lbl_ktx_warn.pack_forget()  # 초기 숨김

        # ── 구간 프레임 (단일 / BOTH 전환) ───────────────
        self.frm_single = ttk.Frame(top)
        self.frm_single.grid(row=1, column=0, columnspan=4, sticky="ew")
        self._build_single_route(self.frm_single)

        self.frm_both = ttk.Frame(top)
        self.frm_both.grid(row=1, column=0, columnspan=4, sticky="ew")
        self._build_both_route(self.frm_both)
        self.frm_both.grid_remove()          # 초기엔 숨김

        # ── 공통 설정 ────────────────────────────────────
        ttk.Label(top, text="출발일").grid(row=2, column=0, sticky="w", **PAD)
        self.var_date = tk.StringVar(value=dt_date.today().strftime("%Y%m%d"))
        ttk.Entry(top, textvariable=self.var_date, width=12).grid(row=2, column=1, sticky="w", **PAD)
        ttk.Label(top, text="YYYYMMDD 또는 MMDD", foreground="gray").grid(row=2, column=2, sticky="w")

        ttk.Label(top, text="시작 시각").grid(row=3, column=0, sticky="w", **PAD)
        self.var_time = tk.StringVar(value="08")
        ttk.Entry(top, textvariable=self.var_time, width=12).grid(row=3, column=1, sticky="w", **PAD)
        ttk.Label(top, text="HH 또는 HH:MM 이후 열차 검색", foreground="gray").grid(row=3, column=2, sticky="w")

        ttk.Label(top, text="성인 인원").grid(row=4, column=0, sticky="w", **PAD)
        self.var_adult = tk.StringVar(value="1")
        ttk.Spinbox(top, from_=1, to=9, textvariable=self.var_adult, width=5).grid(row=4, column=1, sticky="w", **PAD)

        ttk.Label(top, text="좌석 등급").grid(row=4, column=2, sticky="w", **PAD)
        self.var_seat = tk.StringVar(value="일반실")
        ttk.Combobox(top, textvariable=self.var_seat, values=["일반실", "특실"],
                     state="readonly", width=8).grid(row=4, column=3, sticky="w", **PAD)

        ttk.Label(top, text="재시도 간격(초)").grid(row=5, column=0, sticky="w", **PAD)
        self.var_interval = tk.StringVar(value="5")
        ttk.Spinbox(top, from_=1, to=60, textvariable=self.var_interval, width=5).grid(row=5, column=1, sticky="w", **PAD)

        self.var_pay = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="예약 성공 시 자동결제", variable=self.var_pay).grid(
            row=5, column=2, columnspan=2, sticky="w", **PAD)

        # ── 버튼 ─────────────────────────────────────────
        btn_frm = ttk.Frame(self)
        btn_frm.grid(row=1, column=0, pady=6)

        self.btn_start = ttk.Button(btn_frm, text="▶  예약 시작", command=self._start, width=18)
        self.btn_start.pack(side="left", padx=6)

        self.btn_stop = ttk.Button(btn_frm, text="■  중지", command=self._stop, width=12, state="disabled")
        self.btn_stop.pack(side="left", padx=6)

        self.var_status = tk.StringVar(value="대기 중")
        self.lbl_status = ttk.Label(btn_frm, textvariable=self.var_status, width=20, anchor="w")
        self.lbl_status.pack(side="left", padx=10)

        # ── 로그 ─────────────────────────────────────────
        log_frm = ttk.LabelFrame(self, text="로그", padding=6)
        log_frm.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 12))

        self.log_box = scrolledtext.ScrolledText(log_frm, width=82, height=20,
                                                  state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_config("INFO",    foreground="#d4d4d4")
        self.log_box.tag_config("WARNING", foreground="#f0c040")
        self.log_box.tag_config("ERROR",   foreground="#f07070")
        self.log_box.configure(background="#1e1e1e")

    def _build_single_route(self, parent):
        """단일 열차(KTX 또는 SRT) 구간 입력 행."""
        PAD = dict(padx=10, pady=4)
        ttk.Label(parent, text="출발역").grid(row=0, column=0, sticky="w", **PAD)
        self.var_dep = tk.StringVar(value="수서")
        ttk.Entry(parent, textvariable=self.var_dep, width=12).grid(row=0, column=1, sticky="w", **PAD)
        ttk.Label(parent, text="도착역").grid(row=0, column=2, sticky="w", **PAD)
        self.var_arr = tk.StringVar(value="부산")
        ttk.Entry(parent, textvariable=self.var_arr, width=12).grid(row=0, column=3, sticky="w", **PAD)

    def _build_both_route(self, parent):
        """BOTH 모드 - KTX / SRT 구간 각각 입력."""
        PAD = dict(padx=10, pady=4)

        ttk.Label(parent, text="KTX 출발역").grid(row=0, column=0, sticky="w", **PAD)
        self.var_ktx_dep = tk.StringVar(value="서울")
        ttk.Entry(parent, textvariable=self.var_ktx_dep, width=10).grid(row=0, column=1, sticky="w", **PAD)
        ttk.Label(parent, text="KTX 도착역").grid(row=0, column=2, sticky="w", **PAD)
        self.var_ktx_arr = tk.StringVar(value="부산")
        ttk.Entry(parent, textvariable=self.var_ktx_arr, width=10).grid(row=0, column=3, sticky="w", **PAD)

        ttk.Label(parent, text="SRT 출발역").grid(row=1, column=0, sticky="w", **PAD)
        self.var_srt_dep = tk.StringVar(value="수서")
        ttk.Entry(parent, textvariable=self.var_srt_dep, width=10).grid(row=1, column=1, sticky="w", **PAD)
        ttk.Label(parent, text="SRT 도착역").grid(row=1, column=2, sticky="w", **PAD)
        self.var_srt_arr = tk.StringVar(value="부산")
        ttk.Entry(parent, textvariable=self.var_srt_arr, width=10).grid(row=1, column=3, sticky="w", **PAD)

    def _on_type_change(self):
        """열차 종류 변경 시 구간 프레임 전환."""
        t = self.var_type.get()
        if t == "BOTH":
            self.frm_single.grid_remove()
            self.frm_both.grid()
        else:
            self.frm_both.grid_remove()
            self.frm_single.grid()
        if t in ("KTX", "BOTH"):
            self.lbl_ktx_warn.pack(side="left", padx=10)
        else:
            self.lbl_ktx_warn.pack_forget()

    def _setup_logging(self):
        handler = TextHandler(self.log_box)
        logging.root.setLevel(logging.INFO)
        logging.root.addHandler(handler)

    # ── 입력값 수집 ───────────────────────────────────────
    def _collect_settings(self):
        from main import validate_date, validate_time

        date_str = validate_date(self.var_date.get().strip())
        if len(date_str) != 8:
            raise ValueError(f"날짜 형식 오류: {self.var_date.get()}")

        time_str = validate_time(self.var_time.get().strip())
        if len(time_str) != 6:
            raise ValueError(f"시각 형식 오류: {self.var_time.get()}")

        train_type = self.var_type.get()
        common = dict(
            date=date_str,
            time_str=time_str,
            adult=int(self.var_adult.get()),
            seat_type=self.var_seat.get(),
            retry_interval=int(self.var_interval.get()),
            max_retry=0,
            auto_payment=self.var_pay.get(),
        )

        if train_type == "BOTH":
            ktx_kw = dict(common, departure=self.var_ktx_dep.get().strip(),
                          destination=self.var_ktx_arr.get().strip())
            srt_kw = dict(common, departure=self.var_srt_dep.get().strip(),
                          destination=self.var_srt_arr.get().strip())
            return {"train_type": "BOTH", "ktx_kwargs": ktx_kw, "srt_kwargs": srt_kw}

        return dict(train_type=train_type,
                    departure=self.var_dep.get().strip(),
                    destination=self.var_arr.get().strip(),
                    **common)

    # ── 예약 시작 ─────────────────────────────────────────
    def _start(self):
        try:
            settings = self._collect_settings()
        except ValueError as e:
            logging.error(str(e))
            return

        self._stop_event = threading.Event()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._set_status("실행 중...", "#4ec94e")

        def worker():
            from main import run_booking
            train_type = settings.pop("train_type")
            if train_type == "BOTH":
                ktx_kw = settings["ktx_kwargs"]
                srt_kw = settings["srt_kwargs"]
                success = run_booking("BOTH", {}, ktx_kwargs=ktx_kw, srt_kwargs=srt_kw,
                                      stop_event=self._stop_event)
            else:
                kw = {k: v for k, v in settings.items()}
                kw["_stop_event"] = self._stop_event
                success = run_booking(train_type, kw)
            self.after(0, self._on_done, success)

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def _stop(self):
        if self._stop_event:
            self._stop_event.set()
        self._set_status("중지됨", "#f0c040")
        self._reset_buttons()

    def _on_done(self, success: bool):
        self._reset_buttons()
        self._set_status("예약 완료!" if success else "실패 / 중지",
                         "#4ec94e" if success else "#f07070")

    def _reset_buttons(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def _set_status(self, text: str, color: str = "#d4d4d4"):
        self.var_status.set(text)
        self.lbl_status.configure(foreground=color)


if __name__ == "__main__":
    app = App()
    app.mainloop()
