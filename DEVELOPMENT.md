# RoboTrader 개발자 가이드

## 데이터 흐름

### 실시간 매매 흐름 (price_position 전략)
```
1. 프리마켓 분석 (pre_market_analyzer.py) — _pre_market_task()
   - NXT 스냅샷 수집 → 시장 심리 판단
   - 서킷브레이커 체크 (전일 지수 + NXT 갭)
   ↓
2. 실시간 종목 스크리너 (stock_screener.py)
   - Phase 1: KOSPI+KOSDAQ 거래량순위 API (4회 호출) → ~80-100개 후보
   - Phase 2: 기본 필터 (등락률, 가격, 거래대금) → ~20-30개
   - Phase 3: 현재가 API 정밀 검증 (시가대비 0.8~4.0%, 갭 <3%) → 최대 5개 추가
   ↓
   ┌────────────── 매수 트랙 ──────────────┐  ┌──── 매도 트랙 ────┐
   │                                        │  │                    │
3. _system_monitoring_task() (매 13~45초)    │  │ _trading_decision_ │
   → _update_intraday_data()                │  │ task() (매 5초)    │
     → intraday_manager.batch_update_       │  │ → 손절/익절 체크   │
       realtime_data()                      │  │ → 장마감 청산      │
     → 캔들 완성 시점에만 매수 판단 실행    │  │ → emergency_sync   │
   ↓                                        │  └────────────────────┘
4. 가격 위치 전략 평가 (price_position_strategy.py)
   - 시가 대비 1~3% 상승 구간 확인
   - 진입 시간(9~12시), 변동성/모멘텀 필터
   ↓
5. 매매 판단 (trading_decision_engine.py)
   ↓
6. 주문 실행 (trade_executor.py → order_manager.py)
   ↓
7. 포지션 관리 (trading_stock_manager.py)
   - 손절 -5%, 익절 +6%, 장마감 청산 (15:00)
   ↓
8. 장 마감 데이터 저장 (post_market_data_saver.py)
   - 분봉/일봉 저장 + 지수 일봉 자동 저장 (yfinance)
```

> **주의**: 매수 판단은 `_trading_decision_task()`가 아닌 `_system_monitoring_task()` → `_update_intraday_data()`에서 캔들 완성 시점(minute % interval == 0, second >= 10)에 트리거됩니다. `_trading_decision_task()`는 매도 판단과 포지션 동기화만 담당합니다.

---

## 실시간 vs 시뮬레이션 차이

| 구분 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| **데이터 소스** | KIS API (실시간) | PostgreSQL (확정) |
| **종목 발굴** | 스크리너 3단계 전체 | 스크리너 Phase 1~2만 (Phase 3 미적용) |
| **분봉 업데이트** | 지속적 업데이트 | 고정된 종가 |
| **서킷브레이커** | NXT + 전일 지수 | 전일 지수만 |

> **참고**: 시뮬이 실거래보다 낙관적인 가장 큰 원인은 스크리너 Phase 3 미적용 (후보 풀이 다름)

---

## 디버깅 체크리스트

### 거래 0건 원인 확인 순서
```bash
# 1. 서킷브레이커 발동 여부
grep "서킷브레이커" logs/trading_YYYYMMDD.log

# 2. 최대 종목 수 도달 (실제 로그 형식: "동시 보유 최대 N종목 도달")
grep "동시 보유 최대.*종목 도달" logs/trading_YYYYMMDD.log

# 3. 시가 대비 범위 미충족
grep "시가 대비" logs/trading_YYYYMMDD.log

# 4. 고급 필터 차단
grep "고급 필터 차단" logs/trading_YYYYMMDD.log
```

### 실시간 거래 로그 분석
```bash
# 매수 신호 (실제: "🚀 [가격위치전략] 매수 신호!")
grep "가격위치전략.*매수 신호" logs/trading_YYYYMMDD.log

# 매수 주문 실행 (실제: "🔥 XXXXXX 실제 매수 주문 완료: N주 @가격원")
grep "실제 매수 주문 완료" logs/trading_YYYYMMDD.log

# 스크리너 결과
grep "\[스크리너\]" logs/trading_YYYYMMDD.log

# 프리마켓 리포트
grep "프리마켓 리포트" logs/trading_YYYYMMDD.log
```

### 캐시 데이터 확인
```python
import psycopg2
import pandas as pd

conn = psycopg2.connect(host='localhost', port=5433, database='robotrader',
                        user='postgres', password='your_password')
df = pd.read_sql_query('''
    SELECT * FROM minute_candles
    WHERE stock_code = 'XXXXXX' AND trade_date = 'YYYYMMDD'
    ORDER BY idx
''', conn)
print(df)
conn.close()
```

---

## 로그 파일 구조

### 실시간 거래 로그
**위치**: `logs/trading_YYYYMMDD.log`

**주요 메시지** (실제 코드 기반):
```
✅ 006280(녹십자) 선정 완료 - 시간: 10:45:29           # trading_stock_manager.py
🚀 [가격위치전략] 매수 신호!                            # trading_decision_engine.py (INFO)
🔥 006280 실제 매수 주문 완료: 10주 @12,500원           # trade_executor.py (INFO)
✅ 006280 매수 완료                                     # trading_stock_manager.py (INFO)
```

---

## PostgreSQL 캐시 시스템

### 테이블 구조
- **분봉 데이터**: `minute_candles` (PK: stock_code, trade_date, idx)
- **일봉 데이터**: `daily_candles` (PK: stock_code, stck_bsop_date)
  - 지수(KS11, KQ11) 일봉도 여기에 저장 (서킷브레이커용)

### 캐시 클래스
- `DataCache` (utils/data_cache.py): 분봉 데이터
- `DailyDataCache` (utils/data_cache.py): 일봉 데이터

---

## 시뮬레이션

```bash
# 스크리너 통합 시뮬레이션 (추천)
python simulate_with_screener.py --start 20250224 --end 20260223

# 데이터 수집 + 시뮬레이션 파이프라인
python collect_and_simulate.py --phase ABCD --start 20250224 --end 20260223
# Phase A: 일봉 수집, Phase B: 스크리너 후보 선정
# Phase C: 분봉 수집 (KIS API → PostgreSQL), Phase D: 시뮬레이션 실행
```

---

## 관련 문서

- [ROBOTRADER_ANALYSIS_GUIDE.md](ROBOTRADER_ANALYSIS_GUIDE.md) - 분석 가이드 상세
- [docs/stock_state_management.md](docs/stock_state_management.md) - 종목 상태 관리
- [docs/pre_market_circuit_breaker.md](docs/pre_market_circuit_breaker.md) - 서킷브레이커 상세
