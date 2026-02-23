# RoboTrader 개발자 가이드

## 데이터 흐름

### 실시간 매매 흐름
```
1. KIS API → 1분봉 데이터 수집 (data_collector.py)
   ↓
2. 3분봉 변환 (TimeFrameConverter)
   ↓
3. 눌림목 패턴 분석 (pullback_candle_pattern.py)
   ↓
4. pattern_stages 생성:
   - 1_uptrend: 상승 구간 (price_gain, candle_count)
   - 2_decline: 하락 구간 (decline_pct, candle_count)
   - 3_support: 지지 구간 (candle_count)
   - 4_breakout: 돌파봉 (idx)
   ↓
5. 고급 필터 검사 (advanced_filters.py)
   ↓
6. ML 필터 검사 (선택적, ml_settings.py)
   ↓
7. 매매 판단 (trading_decision_engine.py)
   ↓
8. 주문 실행 (order_manager.py)
```

### pattern_stages 데이터 흐름 (실시간)
```python
# 1. 패턴 감지 (pullback_candle_pattern.py:433)
PullbackCandlePattern.generate_improved_signals()

# 2. pattern_stages 생성 (pullback_candle_pattern.py:695)
complete_pattern_data['pattern_stages'] = {
    '1_uptrend': {'price_gain': 0.15, 'candle_count': 5},
    '2_decline': {'decline_pct': 3.5, 'candle_count': 3},
    '3_support': {'candle_count': 2},
    '4_breakout': {'idx': 45}
}

# 3. signal_strength에 저장 (pullback_candle_pattern.py:718)
signal_strength.pattern_data = complete_pattern_data

# 4. price_info로 전달 (trading_decision_engine.py:1089)
price_info['pattern_data'] = signal_strength.pattern_data

# 5. pattern_stages 추출 (trading_decision_engine.py:349)
pattern_stages = price_info.get('pattern_data', {}).get('pattern_stages')

# 6. 고급 필터 호출 (trading_decision_engine.py:352)
AdvancedFilterManager.check_signal(pattern_stages=pattern_stages)
```

---

## 실시간 vs 시뮬레이션 차이

| 구분 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| **데이터 소스** | KIS API (실시간) | PostgreSQL (확정) |
| **selection_date 필터** | 없음 | 있음 (선정 시점 이전 차단) |
| **분봉 업데이트** | 지속적 업데이트 | 고정된 종가 |

### selection_date 필터링 로직
```python
# signal_replay.py:456-459
signal_completion_time = datetime_val + pd.Timedelta(minutes=3)
if signal_completion_time < selection_dt:
    continue  # 차단
```

**예시**:
- 종목 선정: 2025-12-18 10:45:30
- 10:42 캔들 완성: 10:45:00
- 10:45:00 < 10:45:30 → **차단**

---

## 디버깅 체크리스트

### 실시간 vs 시뮬 결과가 다를 때

#### 1단계: 신호 발생 시점 확인
```bash
# 실시간
grep "XXXXXX" logs/trading_YYYYMMDD.log | grep "매수 신호 발생"

# 시뮬레이션
grep "XXXXXX" signal_replay_log/signal_new2_replay_YYYYMMDD*.txt
```

#### 2단계: selection_date 확인
```bash
grep "XXXXXX" logs/trading_YYYYMMDD.log | grep "선정 완료"
```

#### 3단계: 패턴 데이터 비교
```bash
# 실시간 패턴
grep "XXXXXX" pattern_data_log/pattern_data_YYYYMMDD.jsonl

# 시뮬 상세 로그
grep -A100 "=== XXXXXX" signal_replay_log/signal_new2_replay_YYYYMMDD*.txt
```

#### 4단계: 캐시 데이터 확인
```python
import psycopg2
import pandas as pd

conn = psycopg2.connect(host='localhost', port=5432, database='robotrader',
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

## 주요 차이 원인

1. **selection_date 필터링**: 시뮬에서 선정 시점 이전 신호 차단
2. **데이터 불일치**: 실시간 업데이트 vs 확정 캐시
3. **ML 확률 차이**: 패턴 구조가 미묘하게 다름

---

## 로그 파일 구조

### 실시간 거래 로그
**위치**: `logs/trading_YYYYMMDD.log`

**주요 메시지**:
```
✅ 006280(녹십자) 선정 완료 - 시간: 10:45:29
🔍 매수 판단 시작: 006280(녹십자)
🤖 [ML 필터] 006280: 67.4% ✅ 통과
🚀 006280(녹십자) 매수 신호 발생
```

### 패턴 데이터 로그
**위치**: `pattern_data_log/pattern_data_YYYYMMDD.jsonl`

**구조**:
```json
{
  "stock_code": "006280",
  "signal_time": "2025-12-18 11:24:00",
  "pattern_stages": {
    "1_uptrend": {"price_gain": 0.034, "candle_count": 15},
    "2_decline": {"decline_pct": 0.89, "candle_count": 3},
    "3_support": {"candle_count": 2},
    "4_breakout": {"idx": 45}
  }
}
```

---

## 빠른 참조 명령어

```bash
# 종목명으로 코드 찾기
grep "녹십자" logs/trading_YYYYMMDD.log | grep -oP "\d{6}" | head -1

# 시간대별 매수 신호 통계
grep "매수 신호 발생" logs/trading_YYYYMMDD.log | grep -oP "\d{2}:\d{2}" | cut -d: -f1 | sort | uniq -c

# ML 필터링 통계
grep "ML 필터" logs/trading_YYYYMMDD.log | grep "통과" | wc -l
grep "ML 필터" logs/trading_YYYYMMDD.log | grep "차단" | wc -l
```

---

## PostgreSQL 캐시 시스템

### 테이블 구조
- **분봉 데이터**: `minute_candles` (PK: stock_code, trade_date, idx)
- **일봉 데이터**: `daily_candles` (PK: stock_code, stck_bsop_date)

### 캐시 클래스
- `DataCache` (utils/data_cache.py): 분봉 데이터
- `DailyDataCache` (utils/data_cache.py): 일봉 데이터

---

## 관련 문서

- [ROBOTRADER_ANALYSIS_GUIDE.md](ROBOTRADER_ANALYSIS_GUIDE.md) - 분석 가이드 상세
- [docs/trading_logic_documentation.md](docs/trading_logic_documentation.md) - 매매 로직 상세
