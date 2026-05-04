# 인시던트 리포트 — macd_cross D+0 당일청산

**일자**: 2026-04-29 (수)
**심각도**: HIGH (전략 가설 위배 / 영구 동작 불능)
**상태**: 코드 패치 완료, 봇 재시작 대기

---

## 요약

`ACTIVE_STRATEGY = 'macd_cross'` 의 **D+2 보유 전략이 단 한 번도 작동하지 않은 채** 운영되고 있었음. 14:31 시장가 매수된 종목이 같은 날 15:00 EOD 일괄청산 dispatcher 에 의해 청산됨. 우연히 양 종목 모두 양봉으로 끝나 자본 손실은 없었으나, 백테스트가 전제한 2영업일 보유 가설과 완전히 다른 매매 빈도가 발생.

---

## 타임라인 (KST)

| 시각 | 이벤트 |
|------|-------|
| 14:31:16 | 425040(티이엠씨) 시장가 매수 체결 — 61주 @16,380원 |
| 14:31:21 | 005010(휴스틸) 시장가 매수 체결 — 143주 @6,970원 |
| 15:00:02 | `🚨 15:00 시장가 일괄매도 시작: 2종목 (POSITIONED=2)` 트리거 |
| 15:00:05 | 425040 매도 체결 — 61주 @16,476원 |
| 15:00:10 | 005010 매도 체결 — 143주 @7,200원 |

---

## 영향

### 직접 손익
| 종목 | 매수 | 매도 | 차익 | 수수료 | 실손익 |
|------|------|------|------|--------|--------|
| 425040 | @16,380 × 61 | @16,476 × 61 | +5,856원 (+0.59%) | 2,090원 | **+3,766원 (+0.38%)** |
| 005010 | @6,970 × 143 | @7,200 × 143 | +32,890원 (+3.30%) | 2,137원 | **+30,753원 (+3.09%)** |
| **합계** | | | | | **+34,519원** |

### 전략적 영향
- **백테스트 가설 위배**: 2영업일 보유 전제로 산출된 모든 백테스트 수치가 실거래에 적용 불가 — 매매 빈도 약 3배, 수수료 누적 손실 위험
- **D+2 morning exit 경로 무용지물**: 09:01~05 자동 청산 로직이 살아있어도 EOD 가 먼저 매도하므로 도달 불가
- **운영 시작일 추정**: 2026-04-27 macd_cross 실거래 전환 (커밋 02d6356f) 이후 모든 매수가 동일 패턴으로 당일청산되었을 가능성 — 별도 조사 필요

---

## 근본 원인

**`main.py:1963` 의 속성명 오타 — `buy_time` 이라는 속성은 존재하지 않음.**

### 수정 전 코드
```python
buy_time = getattr(ts, 'buy_time', None)
if buy_time is None:
    # 매수 시각 미상 → 보수적으로 청산
    to_close.append(ts)
    continue
days_held = int(np.busday_count(buy_time.date(), today))
```

### 실제 모델 구조 (core/models.py:176)
```python
@dataclass
class TradingStock:
    last_buy_time: Optional[datetime] = None  # 매수 체결 시 set_buy_time() 으로 채워짐
    position: Optional[Position] = None       # Position.entry_time 도 매수 시 set
```

`getattr(ts, 'buy_time', None)` 는 **항상 None** 반환 (속성명이 `last_buy_time` 임). 모든 macd_cross 실거래 포지션이 "매수 시각 미상 → 보수적 청산" 분기로 떨어지면서 D+2 보호가 영구 미작동.

### 왜 발견이 늦었나
- 단위 테스트 부재: EOD 격리 보호 로직에 대한 통합 테스트가 `tests/integration/test_macd_cross_live_flow.py` 에 없음 (10건 모두 PASS, 그러나 EOD 보호는 미커버)
- 가시적 손실 부재: 우연히 매수일 종가가 매수가보다 높아 양 종목 모두 익절. 이런 매매가 며칠 지속되어도 표면상 정상으로 보일 수 있음

---

## 수정

**`main.py:1963~1975`**:

```python
# Position.entry_time 우선 (정상 매수 + emergency_sync 둘 다 호환).
# last_buy_time 은 정상 체결에서만 set, 재시작 후 복원 시 None.
buy_time = None
pos = getattr(ts, 'position', None)
if pos is not None:
    buy_time = getattr(pos, 'entry_time', None)
if buy_time is None:
    buy_time = getattr(ts, 'last_buy_time', None)
if buy_time is None:
    # 매수 시각 미상 → 보수적으로 청산
    to_close.append(ts)
    continue
days_held = int(np.busday_count(buy_time.date(), today))
```

**선택 근거**:
- `Position.entry_time` 은 정상 매수와 emergency_sync (재시작 후 DB 복원) 모두에서 set 됨 → 일관됨
- `last_buy_time` 은 정상 매수에서만 set, 재시작 후엔 None → 폴백으로만 사용
- 둘 다 None 인 비정상 케이스는 보수적 청산 (안전망 유지)

---

## 검증

| 항목 | 결과 |
|------|------|
| 파일 syntax check | PASS |
| 기존 통합 테스트 (`tests/integration/test_macd_cross_live_flow.py`, 10건) | 10 PASSED |
| 단위 시뮬 — 정상 매수 | D+0 → PROTECT ✅ |
| 단위 시뮬 — emergency_sync 후 복원 | D+0 → PROTECT ✅ |
| 단위 시뮬 — position/last_buy_time 둘 다 None | 보수적 청산 ✅ |

---

## 후속 조치

### 즉시 (오늘 ~ 내일 09:00 전)
- [x] `main.py:1963` 패치
- [ ] **봇 재시작** — `taskkill //PID $(cat bot.pid) //F && python main.py` (사용자 직접 진행)

### 단기 (이번 주)
- [ ] **EOD 보호 통합 테스트 추가** — `tests/integration/test_macd_cross_live_flow.py` 에 D+0 보호 / D+2 청산 검증 케이스 추가
- [ ] **2026-04-27 ~ 28 매매 기록 점검** — `real_trading_records` 에서 macd_cross 거래 중 매수일 = 매도일 인 케이스 식별, 동일 사고 발생 여부 확인

### 중기
- [ ] 속성명 변경 (`last_buy_time` → 명확한 이름) 또는 보호 로직을 메서드로 캡슐화 (`ts.get_buy_time()`) 해서 같은 종류의 오타 재발 방지

---

## 교훈

1. **속성명 오타는 syntax 가 아니라 의미 검증으로만 잡힌다** — `getattr(obj, 'wrong_name', default)` 는 항상 default 를 반환할 뿐 에러를 내지 않으므로, 정적 분석/타입체크가 아닌 통합 테스트로만 발견됨
2. **수익이 났다고 정상 동작이 아니다** — 의도와 다르게 동작했지만 결과가 양호한 경우 더 발견이 어려움. 운영 정상성은 결과가 아닌 트리거 경로 (예: "이 매매가 D+2 청산이었는가") 로 검증되어야 함
3. **운영 전환 시 핵심 안전망 단위 테스트 필수** — 실거래 전환 (2026-04-27) 이전에 EOD 보호 로직 검증이 있었어야 함

---

## 참고

- 패치 변경 라인: `main.py:1963~1975`
- 관련 코드: `_execute_end_of_day_liquidation()` (main.py:1894~)
- 관련 모델: `core/models.py:118~` (Position), `core/models.py:133~` (TradingStock)
- macd_cross 실거래 전환 커밋: `02d6356f` (2026-04-27)
