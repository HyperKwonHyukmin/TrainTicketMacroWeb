# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SRT 열차 자동 예매 매크로. GitHub Actions를 통해 서버 없이 웹에서 실행 가능.

## Commands

```bash
pip install SRTrain python-dotenv urllib3 requests

# 로컬 실행 (CLI)
python main.py --type SRT --dep 수서 --arr 부산 --date 20260401 --time 080000

# GitHub Actions 실행
python run_github.py  # 환경 변수에서 파라미터 읽음
```

## Architecture

- `srt_macro.py` — SRT 예매 핵심 로직. `run()` 함수가 로그인 → 열차 검색 → 예약 재시도 루프를 담당
- `station_resolver.py` — 사용자 입력 역명을 SRT 공식 역명으로 변환 (예: "울산" → "울산(통도사)")
- `run_github.py` — GitHub Actions 전용 진입점. 환경 변수(`DEPARTURE`, `DESTINATION`, `DATE` 등)를 읽어 `srt_macro.run()` 호출
- `.github/workflows/srt_booking.yml` — `workflow_dispatch`로 수동 트리거. `SRT_ID`/`SRT_PW`는 GitHub Secrets에서 주입
- `main.py` — 로컬 CLI/GUI 진입점 (KTX + SRT 양쪽 지원)
- `gui.py` — tkinter 데스크톱 GUI (로컬 전용)
- `ktx_macro.py` — KTX는 Korail API가 매크로를 서버 차단 중으로 현재 비작동

## Key Notes

- `auto_payment`는 `run_github.py`에서 항상 `False`로 고정 (실제 카드 결제 방지)
- SRT 라이브러리 패키지명: `SRTrain` (pip), import명: `SRT`
- `requirements.txt`에 `SRTrain` 대신 `korail2`가 있으나 GitHub Actions workflow에서는 `SRTrain`을 직접 설치
