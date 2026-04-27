# macd_cross 실거래 운영 가이드

**상태**: 2026-04-27 실거래 단일 운영 시작. 전 전략(weighted_score / closing_trade / pullback) 폐기.

설계서: [docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md](superpowers/specs/2026-04-26-macd-cross-live-integration-design.md)

---

## 핵심 설정 (config/strategy_settings.py)

```python
ACTIVE_STRATEGY = 'macd_cross'                  # 단일 활성
PAPER_STRATEGY  = None

class MacdCross:
    FAST_PERIOD = 14
    SLOW_PERIOD = 34
    SIGNAL_PERIOD = 12
    ENTRY_HHMM_MIN = 1431                       # 백테스트 next_bar_open 정렬
    ENTRY_HHMM_MAX = 1500
    HOLD_DAYS = 2                               # KRX 영업일
    BUY_BUDGET_RATIO = 0.20                     # 자본 1/N (실 잔고 × 20%)
    MAX_DAILY_POSITIONS = 5
    UNIVERSE_TOP_N = 30
    VIRTUAL_ONLY = False                        # 실 주문 활성
    APPLY_LIVE_OVERLAY = False                  # G1 (라이브 필터 미적용)
```

---

## 운영 정책 (2026-04-27 결정)

| 항목 | 결정 |
|------|------|
| 자금 사이즈 | (가용잔고) / (남은 슬롯) 동적 분할, 최대 5종목 |
| 주문 유형 | 시장가 (14:31:00 분봉 시작) |
| 진입 가드 | 백테스트 가드만 (1일 1회·5포지션·거래량). SL/TP·25분 쿨다운 미적용 |
| 위험 오버레이 | 전일 -3% 서킷브레이커만 inherit (자본 보호 absolute) |
| 청산 | D+2 영업일 09:01~05 시장가 + EOD(15:00) 안전망 |
| 폴백 | 없음. 킬 스위치 발동 시 ACTIVE_STRATEGY 동작 정지 |
| 킬 스위치 | 누적 -5% 또는 5연속 손실 → `config/macd_cross_kill_switch.json` 디스크 저장 → 매수 영구 정지. 복구 = 파일 삭제 후 봇 재시작 |

---

## 백테스트 OOS 성과 (Phase 3 Stage 2)

- Calmar 54.16, Return +11.66%, MDD 1.99%, Win 61.1%, 36 trades, 열화 ratio 0.62
- 4-pillar audit: 데이터 무결성·일반화·universe 안정성 통과. fragility (top1=56.8%) ⚠️ 잔존.

---

## 코드 구조

| 역할 | 위치 |
|------|------|
| 시그널 모듈 (백테스트 공유) | `core/strategies/macd_cross_signal.py` |
| 라이브 어댑터 | `core/strategies/macd_cross_strategy.py` |
| KPI 모듈 | `core/strategies/macd_cross_kpi.py` |
| 모드 디스패처 | `main.py::_macd_cross_mode()` (`'real' | 'virtual' | 'off'`) |
| 매수 경로 | `main.py::_evaluate_macd_cross_window` |
| 매도 경로 | `main.py::_macd_cross_exit_dispatcher` → `_macd_cross_paper_exit_task` 또는 `_macd_cross_live_exit_task` |
| 서킷브레이커 | `main.py::_macd_cross_circuit_breaker_blocks` (전일 -3%) |
| 킬 스위치 | `main.py::_check_macd_cross_kill_switch_thresholds` (EOD 호출) |
| 포지션 동기화 | `main.py::emergency_sync_positions` (strategy_tag 복원) |
| 늦은 시작 보강 | `main.py::_late_start_macd_cross_recovery` (장중 재시작 시 universe prep) |

---

## 운영 명령어

| 작업 | 명령 |
|------|------|
| 실거래 → 가상 회귀 | `MacdCross.VIRTUAL_ONLY = True` + 봇 재시작 |
| 가상 → 실거래 전환 | `MacdCross.VIRTUAL_ONLY = False` + 봇 재시작 |
| 킬 스위치 복구 | `rm config/macd_cross_kill_switch.json` + 봇 재시작 |
| 자동 실행 | `D:/GIT/run_all_robotraders.bat` 의 RoboTrader 라인 활성화 |

---

## 일일 흐름

| 시각 | 이벤트 |
|------|--------|
| 08:55 | universe (top 30 거래대금) 선정 + MACD 캐시 30/30 |
| 09:00 | 개장. KOSPI/KOSDAQ 전일 -3% 미만이면 macd_cross 활성 |
| 14:31 | 시그널 평가 (분봉 마감 시점 골든크로스) → 시장가 매수 |
| 15:00 | EOD. macd_cross 보유분 중 D+2 미도달은 보호, 도달은 청산 |
| D+2 09:01~05 | 보유분 시장가 청산 (KRX 영업일 기준) |

---

## 폐기 전략 정리 일정

- **weighted_score / closing_trade / pullback**: 2026-04-27 폐기. 핵심 코드 삭제 완료. 차트 의존 잔존 코드 (`core/indicators/pullback*`, `price_calculator.py`, `visualization/*`) 는 1주 안정 운영 후 정리 예정.
- **price_position**: 2026-04-21 완전 삭제됨.
