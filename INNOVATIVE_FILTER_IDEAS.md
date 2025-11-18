# 패배 대폭 감소를 위한 혁신적 필터 아이디어

**목표**: 승리는 소폭 줄이고(10-20%), 패배는 대폭 줄이기(30-50%)

---

## 📊 현재 상황 분석

### 시간대별 성과 (필터 있음 기준)

| 시간대 | 거래 수 | 승률 | 패배율 | 평가 |
|--------|---------|------|--------|------|
| 09시 | 109건 | **57.8%** | 42.2% | ✅ 안전 |
| 10시 | 181건 | **48.1%** | 51.9% | ⚠️ 위험 |
| 11시 | 61건 | 50.8% | 49.2% | ⏸️ 보통 |
| 12시 | 6건 | 50.0% | 50.0% | ⏸️ 보통 |
| 14시 | 30건 | **43.3%** | 56.7% | 🚫 고위험 |

**핵심 발견**:
1. **10시와 14시가 손실의 주범** (패배율 50% 이상)
2. 09시는 가장 안전한 시간대 (승률 57.8%)
3. 전체 거래의 47%가 10시에 발생

---

## 💡 혁신적 필터 아이디어

### 🥇 아이디어 1: 시간대 가중치 필터 (TIME_WEIGHT_FILTER)

**핵심 개념**: 시간대별로 다른 필터 강도 적용

```python
class TimeWeightedFilter:
    """시간대별 필터 강도 조정"""

    def __init__(self):
        self.time_weights = {
            9: {'close_pos': 0.55, 'volume': 1.2, 'risk': 'LOW'},
            10: {'close_pos': 0.65, 'volume': 1.5, 'risk': 'HIGH'},
            11: {'close_pos': 0.60, 'volume': 1.3, 'risk': 'MEDIUM'},
            12: {'close_pos': 0.60, 'volume': 1.3, 'risk': 'MEDIUM'},
            14: {'close_pos': 0.70, 'volume': 2.0, 'risk': 'VERY_HIGH'}
        }

    def should_pass(self, hour, close_position, volume_ratio):
        weight = self.time_weights.get(hour, {'close_pos': 0.65, 'volume': 1.5})

        # 시간대별 최소 기준 체크
        if close_position < weight['close_pos']:
            return False

        if volume_ratio < weight['volume']:
            return False

        return True
```

**예상 효과**:
- 10시 거래 감소: 181건 → 120건 (-34%)
- 14시 거래 감소: 30건 → 10건 (-67%)
- 전체 승률: 50.9% → 55-58%
- **패배 감소: 40-50%**

---

### 🥈 아이디어 2: 위험 점수 시스템 (RISK_SCORE_SYSTEM)

**핵심 개념**: 여러 지표를 종합하여 위험 점수 계산

```python
class RiskScoreFilter:
    """종합 위험 점수 평가"""

    def calculate_risk_score(self, trade_info):
        """위험 점수 계산 (0-100, 낮을수록 위험)"""
        score = 100

        # 1. 시간대 리스크 (-20~0)
        hour_risk = {9: 0, 10: -15, 11: -10, 12: -10, 14: -20}
        score += hour_risk.get(trade_info['hour'], -15)

        # 2. 종가 위치 (0~+20)
        close_pos = trade_info['close_position']
        if close_pos >= 70:
            score += 20
        elif close_pos >= 65:
            score += 15
        elif close_pos >= 60:
            score += 10
        elif close_pos >= 55:
            score += 5
        else:
            score -= 10

        # 3. 거래량 증가율 (0~+15)
        volume_ratio = trade_info['volume_ratio']
        if volume_ratio >= 200:
            score += 15
        elif volume_ratio >= 100:
            score += 10
        elif volume_ratio >= 50:
            score += 5
        else:
            score -= 5

        # 4. 상승 구간 강도 (0~+15)
        uptrend_gain = trade_info.get('uptrend_gain', 0)
        if uptrend_gain >= 10:
            score += 15
        elif uptrend_gain >= 7:
            score += 10
        elif uptrend_gain >= 5:
            score += 5
        else:
            score -= 5

        # 5. 캔들 실체 비율 (0~+10)
        body_ratio = trade_info.get('body_ratio', 0.5)
        if body_ratio >= 0.7:
            score += 10
        elif body_ratio >= 0.6:
            score += 5
        else:
            score -= 5

        return max(0, min(100, score))

    def should_pass(self, trade_info):
        score = self.calculate_risk_score(trade_info)

        # 점수 기준
        if score >= 80:
            return True, "HIGH_QUALITY"
        elif score >= 70:
            return True, "MEDIUM_QUALITY"
        elif score >= 60:
            return True, "LOW_QUALITY"
        else:
            return False, f"TOO_RISKY (score: {score})"
```

**예상 효과**:
- 다차원 평가로 정밀한 필터링
- 승률: 50.9% → 58-62%
- **패배 감소: 45-55%**

---

### 🥉 아이디어 3: 적응형 필터 (ADAPTIVE_FILTER)

**핵심 개념**: 최근 성과에 따라 필터 강도 동적 조정

```python
class AdaptiveFilter:
    """최근 성과 기반 적응형 필터"""

    def __init__(self):
        self.recent_trades = []  # 최근 10개 거래
        self.base_threshold = 0.60

    def update_trades(self, trade_result):
        """거래 결과 업데이트"""
        self.recent_trades.append(trade_result)
        if len(self.recent_trades) > 10:
            self.recent_trades.pop(0)

    def get_current_threshold(self):
        """현재 필터 강도 계산"""
        if len(self.recent_trades) < 5:
            return self.base_threshold

        # 최근 승률 계산
        wins = sum(1 for t in self.recent_trades if t['is_win'])
        recent_win_rate = wins / len(self.recent_trades)

        # 승률에 따라 필터 강도 조정
        if recent_win_rate < 0.40:  # 승률 40% 미만
            # 필터 강화 (거래 줄이기)
            return self.base_threshold + 0.10  # 70%
        elif recent_win_rate < 0.50:  # 승률 50% 미만
            return self.base_threshold + 0.05  # 65%
        elif recent_win_rate > 0.60:  # 승률 60% 이상
            # 필터 완화 (거래 늘리기)
            return self.base_threshold - 0.05  # 55%
        else:
            return self.base_threshold  # 60%

    def should_pass(self, close_position):
        threshold = self.get_current_threshold()
        return close_position >= threshold
```

**예상 효과**:
- 손실 구간에서 자동으로 방어적 전환
- 승률: 50.9% → 54-57%
- **패배 감소: 30-40%**

---

### 🌟 아이디어 4: 연속 패배 브레이크 (LOSING_STREAK_BREAKER)

**핵심 개념**: 연속 손실 시 거래 일시 중지

```python
class LosingStreakBreaker:
    """연속 손실 방지 시스템"""

    def __init__(self):
        self.today_trades = []
        self.max_consecutive_losses = 2

    def add_trade(self, trade_result):
        self.today_trades.append(trade_result)

    def should_pause_trading(self):
        """거래 중지 여부 판단"""
        if len(self.today_trades) < 2:
            return False

        # 최근 2개 연속 손실?
        recent_2 = self.today_trades[-2:]
        if all(not t['is_win'] for t in recent_2):
            return True, "연속 2회 손실 - 오늘 거래 중지"

        # 오늘 5회 이상 거래 & 승률 30% 이하?
        if len(self.today_trades) >= 5:
            wins = sum(1 for t in self.today_trades if t['is_win'])
            win_rate = wins / len(self.today_trades)
            if win_rate < 0.30:
                return True, f"승률 저조({win_rate:.1%}) - 오늘 거래 중지"

        return False, None

    def reset_daily(self):
        """일일 초기화"""
        self.today_trades = []
```

**예상 효과**:
- 손실 확대 방지
- 심리적 안정
- **패배 감소: 20-30%**

---

### 💎 아이디어 5: 조합 필터 (COMBO_FILTER) - 최종 권장

**핵심 개념**: 위 아이디어들을 조합

```python
class ComboFilter:
    """종합 필터 시스템"""

    def __init__(self):
        self.time_filter = TimeWeightedFilter()
        self.risk_filter = RiskScoreFilter()
        self.adaptive_filter = AdaptiveFilter()
        self.streak_breaker = LosingStreakBreaker()

    def should_allow_trade(self, trade_info):
        """거래 허용 여부 판단 (다단계 필터링)"""

        # 1단계: 연속 손실 체크 (최우선)
        is_paused, reason = self.streak_breaker.should_pause_trading()
        if is_paused:
            return False, reason

        # 2단계: 시간대 가중치 체크
        if not self.time_filter.should_pass(
            trade_info['hour'],
            trade_info['close_position'],
            trade_info['volume_ratio']
        ):
            return False, "시간대 필터 차단"

        # 3단계: 위험 점수 평가
        allowed, risk_reason = self.risk_filter.should_pass(trade_info)
        if not allowed:
            return False, risk_reason

        # 4단계: 적응형 필터 (최근 성과 기반)
        threshold = self.adaptive_filter.get_current_threshold()
        if trade_info['close_position'] < threshold:
            return False, f"적응형 필터 차단 (임계값: {threshold:.1%})"

        return True, "모든 필터 통과"
```

**예상 효과**:
- 승률: 50.9% → **60-65%**
- 거래 감소: 387건 → 250건 (-35%)
- **패배 감소: 50-60%** ⭐
- **승리 감소: 15-25%** (목표 달성)

---

## 📊 필터별 비교

| 필터 | 난이도 | 구현 시간 | 예상 승률 | 패배 감소 | 승리 감소 |
|------|--------|----------|----------|-----------|----------|
| 시간대 가중치 | ⭐ | 1일 | 55-58% | 40-50% | 15-20% |
| 위험 점수 | ⭐⭐ | 2-3일 | 58-62% | 45-55% | 20-25% |
| 적응형 | ⭐⭐⭐ | 3-4일 | 54-57% | 30-40% | 10-15% |
| 연속 손실 방지 | ⭐ | 1일 | 52-54% | 20-30% | 5-10% |
| **조합 필터** | **⭐⭐⭐** | **5-7일** | **60-65%** | **50-60%** | **15-25%** |

---

## 🎯 구현 로드맵

### Phase 1 (1주일): 빠른 승리
1. **시간대 가중치 필터** 구현
2. **연속 손실 브레이크** 구현
3. 1주일 백테스트로 효과 검증

**목표**: 승률 54-56% 달성

### Phase 2 (2주일): 성능 극대화
1. **위험 점수 시스템** 구현
2. **적응형 필터** 구현
3. 조합 테스트 및 최적화

**목표**: 승률 58-62% 달성

### Phase 3 (3주일): 완성 및 안정화
1. **조합 필터** 통합
2. 장기 백테스트 (2-3개월)
3. 실전 적용 및 모니터링

**목표**: 승률 60-65% 안정화

---

## 💻 즉시 구현 가능한 코드 (Phase 1)

### 1. 시간대 필터

```python
# core/indicators/time_weighted_filter.py

class TimeWeightedFilter:
    """시간대별 차별화 필터"""

    def __init__(self):
        self.hour_config = {
            9: {'min_close': 0.55, 'min_volume': 1.2},
            10: {'min_close': 0.65, 'min_volume': 1.5},
            11: {'min_close': 0.60, 'min_volume': 1.3},
            12: {'min_close': 0.60, 'min_volume': 1.3},
            14: {'min_close': 0.70, 'min_volume': 2.0}
        }

    def should_exclude(self, debug_info, current_time):
        """시간대별 필터 적용"""
        hour = current_time.hour

        if hour not in self.hour_config:
            return False, None

        config = self.hour_config[hour]
        breakout = debug_info.get('best_breakout', {})

        # 종가 위치 체크
        close_position = self._get_close_position(breakout)
        if close_position < config['min_close']:
            return True, f"{hour:02d}시 종가 위치 부족: {close_position:.1%} < {config['min_close']:.1%}"

        # 거래량 체크
        volume_ratio = breakout.get('volume_ratio_vs_prev', 1.0)
        if volume_ratio < config['min_volume']:
            return True, f"{hour:02d}시 거래량 부족: {volume_ratio:.1f}x < {config['min_volume']:.1f}x"

        return False, None

    def _get_close_position(self, breakout):
        """종가 위치 계산"""
        high = breakout.get('high', 0)
        low = breakout.get('low', 0)
        close = breakout.get('close', 0)

        if high == low:
            return 0.5

        return (close - low) / (high - low)
```

### 2. 연속 손실 브레이크

```python
# core/trading/losing_streak_breaker.py

class LosingStreakBreaker:
    """연속 손실 방지"""

    def __init__(self):
        self.today = None
        self.today_trades = []

    def add_trade_result(self, trade_result, trade_date):
        """거래 결과 추가"""
        # 날짜 변경 시 초기화
        if self.today != trade_date:
            self.today = trade_date
            self.today_trades = []

        self.today_trades.append(trade_result)

    def should_pause(self):
        """거래 중지 여부"""
        if len(self.today_trades) < 2:
            return False, None

        # 연속 2회 손실
        recent = self.today_trades[-2:]
        if all(t['profit'] < 0 for t in recent):
            return True, "연속 2회 손실 - 오늘 거래 중지"

        # 5회 이상 & 승률 30% 미만
        if len(self.today_trades) >= 5:
            wins = sum(1 for t in self.today_trades if t['profit'] > 0)
            win_rate = wins / len(self.today_trades)
            if win_rate < 0.30:
                return True, f"승률 저조 {win_rate:.1%} - 오늘 거래 중지"

        return False, None
```

---

## 📝 결론

**최고의 선택**: 조합 필터 (COMBO_FILTER)

**기대 효과**:
- 승률: 50.9% → **60-65%** (+10-15%p)
- 패배: 190건 → **95-114건** (-40~-50%)
- 승리: 197건 → **157-173건** (-12~-20%)
- 거래 빈도: 387건 → 250건 (-35%)

**구현 순서**:
1. 시간대 가중치 필터 (1주)
2. 연속 손실 브레이크 (1주)
3. 위험 점수 시스템 (2주)
4. 최종 통합 및 최적화 (1주)

**총 소요 시간**: 5-7주
**투자 대비 효과**: ⭐⭐⭐⭐⭐
