# 개발 노트 (Claude 세션 학습)

코드를 만지면서 비싸게 발견한 gotcha 모음. 작업 시작 전 일독 권장.

---

## DB 스키마 주의사항

### `daily_prices.date` 는 text 타입 (`YYYY-MM-DD`)

- ❌ `TO_CHAR(date, 'YYYYMMDD')` — `to_char(text, ...)` 함수 매칭 실패
- ✅ `REPLACE(date, '-', '')` — text → text 변환
- 비교는 ISO 정렬이라 text `<` 비교 그대로 가능

### `real_trading_records.strategy` / `virtual_trading_records.strategy`

- 명시적 태그 저장. 누락 시 `trading_stock.selection_reason` 폴백 (오답 위험)
- 신규 전략 추가 시 `strategy_tag` 파라미터 전파 필수 (아래 체인 참조)

---

## PostgreSQL 단일 connection 재사용 (캐스케이드 주의)

루프에서 같은 connection 으로 여러 종목 처리 시 한 쿼리 실패가 트랜잭션을 abort 상태로 들어가게 함 → 후속 모든 쿼리가 `현재 트랜잭션은 중지되어 있습니다` 에러로 캐스케이드.

```python
for code in codes:
    try:
        cur.execute(...)
    except Exception:
        conn.rollback()  # 필수 — 누락 시 다음 종목 모두 실패
        ...
```

`main.py::_load_macd_cross_daily_batch` 가 이 패턴 적용한 사례.

---

## strategy_tag 전파 체인

`real_trading_records.strategy` 컬럼을 정확히 채우려면 매수 호출부터 DB 저장까지 4단계 전파:

```
main.py::_evaluate_macd_cross_window
  → decision_engine.execute_real_buy(..., strategy_tag='macd_cross')
    → trade_executor.execute_real_buy(..., strategy_tag=strategy_tag)
      → trading_manager.execute_buy_order(..., strategy_tag=strategy_tag)
        → trading_stock.strategy_tag 속성 setattr
          → save_real_buy(strategy=trading_stock.strategy_tag or selection_reason)
```

신규 전략 추가 시 이 체인 모두 옵션 파라미터로 통과시켜야 함. 미지정 시 `selection_reason` 폴백 (기존 동작 보존).

---

## 봇 lifecycle

- **PID 파일**: `bot.pid` (자동 갱신)
- **정지**: `taskkill //PID $(cat bot.pid) //F` (Windows). 보유 0종목·미체결 0건이면 force kill 안전.
- **재시작**: `python main.py` (Bash run_in_background:true). 출력은 cp949 console 인코딩으로 깨질 수 있음 — PID/숫자만 정상.
- **장중 재시작 시**: `_restore_pre_market_report` + `_late_start_macd_cross_recovery` 가 `initialize()` 에서 자동 보강 (08:55 정상 경로 누락 보완).

---

## macd_cross 분기 헬퍼

`_macd_cross_mode()` (main.py) 가 `'real' | 'virtual' | 'off'` 반환. 직접 ACTIVE_STRATEGY 비교 대신 이걸로 분기.

| 결과 | 조건 |
|------|------|
| `'real'` | ACTIVE_STRATEGY=='macd_cross' AND VIRTUAL_ONLY=False AND 킬스위치 비활성 |
| `'virtual'` | ACTIVE_STRATEGY=='macd_cross' AND VIRTUAL_ONLY=True, 또는 PAPER_STRATEGY=='macd_cross' |
| `'off'` | 위 모두 미충족 (킬스위치 발동 포함) |

킬 스위치 자동 전환: `'real'` → `'off'` (디스크 `config/macd_cross_kill_switch.json` 체크).

---

## Windows 환경

- 콘솔: cp949. `tasklist`/`taskkill` 한글 출력 깨지지만 PID/숫자는 정상.
- DB 조회: `psql` 미설치. `psycopg2` 파이썬 스크립트 사용 (인코딩 안정성도 +).
- Shell: bash via Git Bash. 경로는 forward slash, 리다이렉트 `/dev/null` (NUL 아님).

---

## 테스트 실행

| 목적 | 명령 | 시간 |
|------|------|------|
| macd_cross 전용 | `python -m pytest tests/integration/test_macd_cross_*.py` | ~2s (13건) |
| 전체 | `python -m pytest tests/` | ~4s (217건) |

리포 루트의 `test_*.py` 파일들은 obsolete 실험 — 무시.

---

## Bash sleep 제한

긴 leading sleep 차단됨. 대안:

- **봇 시작 대기**: `until grep -q "활성 전략: macd_cross" logs/trading_$(date +%Y%m%d).log; do sleep 3; done` + `run_in_background: true`
- **백그라운드 작업 완료 대기**: 알림 자동 도착 (sleep 폴링 금지)
- **Monitor 도구**: 한 번 알림용은 Bash run_in_background, 반복 알림용은 Monitor

---

## 한국 시장 특수일

- EOD 청산: 정상 15:00, 특별일 시프트 (`config/market_hours.py`)
- 영업일: KRX 거래일 기준. `numpy.busday_count` 는 Mon-Fri 만 고려 (한국 공휴일 미반영, 오차 수일/년 허용).
- 더 정확한 영업일: `main.py::_count_krx_trading_days_between` (KRX 휴장일 반영)
