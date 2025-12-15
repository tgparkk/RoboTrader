---
layout: post
title: "트레이딩 시스템에 머신러닝을 적용한 기술 여정"
date: 2025-11-30
categories: machine-learning
tags: [machine-learning, trading, python, lightgbm, 머신러닝, 트레이딩]
excerpt: "한국투자증권 KIS API를 활용한 자동화 트레이딩 시스템 개발 경험을 공유합니다. 초기에는 기술적 지표와 패턴 분석만으로 신호를 생성했지만, 시뮬레이션 결과 정확도가 50%대에 머물렀습니다. 머신러닝을 도입하여 신호 정확도를 70%대까지 개선한 기술적 구현 과정을 다룹니다. 왜 ML이 필요했는지, 어떤 ML 기법들을 적용했는지, 실전에서 마주한 도전과제들을 어떻게 해결했는지, 그리고 ML 모델을 어떻게 지속 가능하게 관리하는지까지 전체 개발 여정을 상세히 공유합니다."
comments: true
---

# 트레이딩 시스템에 머신러닝을 적용한 기술 여정

## 들어가며

이 글은 한국투자증권 KIS API를 활용한 자동화 트레이딩 시스템 개발 경험을 공유합니다. 초기에는 기술적 지표와 패턴 분석만으로 신호를 생성했지만, 시뮬레이션 결과 **정확도가 50%대에 머물렀습니다**. 머신러닝을 도입하여 신호 정확도를 70%대까지 개선한 **기술적 구현 과정**을 다음 순서로 공유합니다:

> ⚠️ **주의**: 이 글은 ML 기술 개발 경험을 공유하는 것이며, 투자 권유나 수익 보장이 아닙니다.

1. **왜 ML이 필요했나?** - 패턴 기반 시스템의 한계와 ML 도입 배경
2. **트레이딩 시스템에 적용 가능한 ML 기법들** - 다양한 ML 모델 비교 및 선택
3. **실전 적용과 성능 개선** - 구현 과정과 결과
4. **ML 모델 관리 전략** - 지속 가능한 운영 방법

---

## 1. 왜 ML이 필요했나?

### 초기 패턴 기반 시스템의 한계

개발한 시스템은 특정 기술적 분석 패턴을 기반으로 합니다:

```
1️⃣ 상승 구간: 가격 상승 + 거래량 감소 추세
2️⃣ 하락 구간: 이등분선 위에서 조정
3️⃣ 지지 구간: 거래량 급감, 캔들 크기 축소
4️⃣ 돌파 구간: 거래량 증가 + 양봉 돌파 → 신호 생성
```

이 패턴은 이론적으로는 타당했지만, **백테스팅 결과 정확도가 50~60%**에 그쳤습니다. 문제는 무엇이었을까요?

#### 규칙 기반 시스템의 한계

```python
# 기존 방식: 하드코딩된 규칙
def should_signal(pattern):
    if (pattern.uptrend_gain > 3.0 and
        pattern.volume_ratio < 0.5 and
        pattern.breakout_volume > threshold):
        return True  # 신호 생성
    return False
```

**문제점:**
- ❌ **정량화의 어려움**: "상승률 3% 이상"은 모든 상황에 적용될까?
- ❌ **복합 변수 미반영**: 시간대, 시장 상황, 여러 비율의 조합을 고려 불가
- ❌ **False Positive 과다**: 패턴은 맞지만 유효하지 않은 신호가 많음
- ❌ **개선의 한계**: 규칙을 하나씩 수정하는 방식은 느리고 비효율적

### ML 적용 전략

핵심 질문: **"패턴은 맞지만, 어떤 패턴이 실제로 유효한가?"**

이 질문에 답하기 위해 머신러닝을 도입했습니다. 목표는 명확했습니다:

```python
# ML 방식: 데이터 기반 학습
def evaluate_signal(pattern_features) -> (bool, float):
    """
    26개의 패턴 특성을 입력받아 신호 유효성 예측

    Returns:
        (신호 허용 여부, 예측 정확도)
    """
    ml_prob = model.predict(pattern_features)  # 0.0 ~ 1.0
    return ml_prob >= 0.5, ml_prob  # 50% 이상이면 허용
```

**ML의 장점:**
- ✅ **자동 패턴 발견**: 사람이 발견하지 못한 복합 규칙 학습
- ✅ **확률적 판단**: 신호 강도를 정량적으로 평가 가능
- ✅ **데이터 기반 개선**: 새로운 데이터로 자동 성능 향상
- ✅ **빠른 의사결정**: 실시간 추론 속도 < 0.001초

### Before vs After 성능 비교

| 지표 | 규칙 기반 | ML 기반 | 개선율 |
|------|-----------|---------|--------|
| **정확도** | 50.6% | **72.9%** | +44% |
| **평균 성능** | 기준 | **1.87배** | +87% |
| **오류 감소** | 49.4% | **27.1%** | -45% |
| **False Positive** | 높음 | **낮음** | - |

---

## 2. 트레이딩 시스템에 적용 가능한 ML 기법들

트레이딩 시스템에 ML을 적용할 때는 **문제 유형**에 따라 적절한 기법을 선택해야 합니다.

### 2.1 문제 유형별 ML 접근법

#### 📊 Type 1: 신호 필터링 (이 프로젝트의 선택)

**목표**: 패턴 신호의 정확도 예측 → 저품질 신호 차단

**적합한 모델:**
- **Gradient Boosting (LightGBM, XGBoost)**: 표 형태 데이터에 최적
- **Random Forest**: 안정적이지만 느림
- **Logistic Regression**: 빠르지만 복잡한 패턴 학습 불가

**이 프로젝트의 선택: LightGBM**

```python
import lightgbm as lgb

params = {
    'objective': 'regression',      # 정확도 예측 (0~1)
    'metric': 'rmse',
    'boosting_type': 'gbdt',
    'num_leaves': 31,
    'learning_rate': 0.05,
    'feature_fraction': 0.9,
    'bagging_fraction': 0.8,
}

model = lgb.train(params, train_set, num_boost_round=1000)
```

**선택 이유:**

| 모델 | 정확도 | 학습 시간 | 추론 속도 | 해석성 | 평가 |
|------|------|----------|----------|--------|------|
| **LightGBM** | **72%** | **1분** | **0.001초** | ⭐⭐⭐ | ✅ **선택** |
| XGBoost | 71% | 3분 | 0.002초 | ⭐⭐⭐ | ⚠️ 근소한 차이 |
| Random Forest | 68% | 5분 | 0.01초 | ⭐⭐ | ❌ 느림 |
| Neural Network | 65% | 10분 | 0.001초 | ⭐ | ❌ 과적합 |
| Logistic Regression | 58% | 10초 | 0.0001초 | ⭐⭐⭐⭐ | ❌ 성능 부족 |

---

#### 🎯 Type 2: 가격 변동 패턴 예측 (연구 중)

**목표**: 시계열 데이터에서 다음 N분 후 가격 변동 패턴 학습

**적합한 모델:**
- **LSTM (Long Short-Term Memory)**: 시계열 데이터 학습
- **GRU (Gated Recurrent Unit)**: LSTM의 경량 버전
- **Transformer**: 최신 시계열 모델 (높은 리소스 필요)

**예시 코드:**

```python
import tensorflow as tf
from tensorflow.keras.layers import LSTM, Dense

# 과거 30분봉 → 다음 3분봉 예측
model = tf.keras.Sequential([
    LSTM(64, input_shape=(30, 5)),  # (시간, 특성)
    Dense(32, activation='relu'),
    Dense(1)  # 예측 가격
])

model.compile(optimizer='adam', loss='mse')
```

**장단점:**
- ✅ 시계열 패턴 학습 가능
- ❌ 데이터 많이 필요 (수만 개 샘플)
- ❌ 학습 시간 오래 걸림
- ❌ 과적합 위험 높음

---

#### 🤖 Type 3: 강화학습 - 의사결정 최적화 (연구 중)

**목표**: 상태에 따른 최적 행동 패턴 학습

**적합한 모델:**
- **DQN (Deep Q-Network)**: 이산 행동 공간
- **PPO (Proximal Policy Optimization)**: 안정적 학습
- **A3C (Asynchronous Actor-Critic)**: 병렬 학습

**개념:**

```python
# 강화학습 프레임워크
class TradingEnv:
    def step(self, action):
        # action: 0=WAIT, 1=ENTER, 2=EXIT
        reward = self.calculate_reward(action)
        next_state = self.get_next_state()
        return next_state, reward, done

# 학습
agent = DQNAgent(state_size=26, action_size=3)
agent.train(env, episodes=10000)

# 추론
action = agent.act(current_state)  # 0, 1, 2
```

**장단점:**
- ✅ 최적 의사결정 패턴 자동 학습
- ✅ 장기 목표 최적화 가능
- ❌ 학습 매우 어려움 (보상 설계)
- ❌ 안정성 낮음 (과적합 위험)
- ❌ 대량 시뮬레이션 필요

---

#### 🔍 Type 4: 이상 패턴 탐지

**목표**: 정상 범위를 벗어난 비정상 패턴 탐지

**적합한 모델:**
- **Isolation Forest**: 이상치 탐지
- **Autoencoder**: 정상 패턴 학습 → 비정상 판별
- **One-Class SVM**: 정상 데이터만으로 학습

**예시:**

```python
from sklearn.ensemble import IsolationForest

# 정상 거래량 패턴 학습
clf = IsolationForest(contamination=0.05)  # 5%를 이상치로 판단
clf.fit(normal_volume_data)

# 이상 탐지
anomaly_score = clf.predict(current_volume)
# -1: 이상 패턴 (비정상), 1: 정상 패턴
```

---

### 2.2 LightGBM 선택 이유

**1. 표 형태 데이터에 최적화**

데이터 구조 예시:

| uptrend_gain | decline_pct | breakout_volume | hour | ... | label |
|--------------|-------------|-----------------|------|-----|-------|
| 3.52 | 1.23 | 162154 | 9 | ... | 1 (성공) |
| 2.87 | 0.95 | 98432 | 10 | ... | 0 (실패) |

→ Tree 기반 모델이 이런 데이터에 강함!

**2. 실시간 추론 속도**

```python
# 속도 비교 (1000회 추론)
LightGBM:      0.12초  ✅
XGBoost:       0.18초
Random Forest: 1.20초  ❌ (실시간 사용 불가)
LSTM:          0.50초
```

장중에 초단위로 판단해야 하므로 속도가 매우 중요합니다.

**3. 해석 가능성 (Feature Importance)**

```python
# 어떤 특성이 중요한지 분석 가능
feature_importance = model.feature_importance()

결과:
1. volume_ratio_support_to_uptrend: 0.18  ← 가장 중요!
2. breakout_body: 0.15
3. hour: 0.12  ← 시간대도 중요
4. uptrend_gain: 0.10
...
```

→ 모델의 판단 근거를 이해할 수 있음 (블랙박스 X)

**4. 과적합 방지**

```python
# Early Stopping으로 과적합 방지
model = lgb.train(
    params,
    train_set,
    num_boost_round=1000,
    valid_sets=[valid_set],
    callbacks=[lgb.early_stopping(50)]  # 50라운드 개선 없으면 중단
)
```

딥러닝 대비 과적합 위험이 훨씬 낮습니다.

---

## 3. 실전 적용과 성능 개선

### 3.1 데이터 수집 파이프라인 구축

ML 모델의 성능은 **데이터 품질**에 달려있습니다.

#### 자동 데이터 수집 시스템

```python
# 1. 실시간 패턴 로깅
class PatternDataLogger:
    """시스템 동작 중 발생한 패턴을 DB에 자동 저장"""

    def log_pattern(self, code, signal_strength):
        pattern_data = {
            'stage_1': {...},    # 1단계 특성
            'stage_2': {...},    # 2단계 특성
            'stage_3': {...},    # 3단계 특성
            'stage_4': {...}     # 4단계 특성
        }
        self.db.insert(pattern_data)
```

```python
# 2. 일일 결과 데이터 생성 (매일 자동 실행)

1. DB에서 당일 패턴 추출
2. 시뮬레이션으로 성공/실패 여부 계산
3. CSV 파일로 저장

결과 예시:
code, time, feature_1, feature_2, ..., label
XXXX, 09:30, 3.52, 1.23, ..., 1 (성공)
YYYY, 10:15, 2.87, 0.95, ..., 0 (실패)
```

**핵심**: 패턴만 저장하는 게 아니라, **실제 결과(성공/실패)**를 함께 기록!

---

### 3.2 특성 엔지니어링 (Feature Engineering)

패턴의 4단계 구조를 **26개 숫자**로 변환했습니다.

#### 주요 특성 설계

**1. 상승 구간 특성 (5개)**

```python
features = {
    'uptrend_candles': 7,           # 상승 봉 개수
    'uptrend_gain': 3.52,           # 상승률 (%)
    'uptrend_max_volume': 250000,   # 최대 거래량
    'uptrend_avg_body': 0.85,       # 평균 몸통 크기 (%)
    'uptrend_total_volume': 1500000 # 총 거래량
}
```

**2. 비율 특성 (5개) - 가장 중요!**

절대값보다 **비율**이 더 중요했습니다:

```python
features = {
    # 하락 시 거래량이 상승 대비 얼마나 줄었는가?
    'volume_ratio_decline_to_uptrend': 0.48,  # ← 높으면 위험

    # 지지 시 거래량이 상승 대비 얼마나 줄었는가?
    'volume_ratio_support_to_uptrend': 0.32,  # ← 낮을수록 좋음!

    # 돌파 시 거래량이 상승 대비 얼마나 증가했는가?
    'volume_ratio_breakout_to_uptrend': 0.65,  # ← 높을수록 좋음

    # 상승 대비 하락이 얼마나 완만했는가?
    'price_gain_to_decline_ratio': 2.86,

    # 지지 기간이 하락 대비 얼마나 길었는가?
    'candle_ratio_support_to_decline': 1.25
}
```

**3. 시간 특성 (6개)**

```python
features = {
    'hour': 9,                      # 시간
    'minute': 30,                   # 분
    'time_in_minutes': 570,         # 분 단위 시간
    'is_morning': 1,                # 오전 여부
    'signal_type': 1,               # STRONG_BUY=1
    'confidence': 85                # 신뢰도
}
```

**분석 결과**: 오전(9~11시) 신호가 더 높은 정확도를 보임

---

### 3.3 학습 및 검증

#### 클래스 불균형 문제 해결

초기 데이터: 성공 60%, 실패 40% → 불균형!

**해결 방법: Stratified K-Fold**

```python
from sklearn.model_selection import StratifiedKFold

# 각 폴드에 성공/실패 비율 유지
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

for train_idx, val_idx in cv.split(X, y):
    X_train, X_val = X[train_idx], X[val_idx]
    y_train, y_val = y[train_idx], y[val_idx]

    # 각 폴드마다 성공/실패 비율 동일하게 유지
    model = lgb.train(params, lgb.Dataset(X_train, y_train))
```

---

### 3.4 실전 적용 시 가장 큰 도전과제

**문제**: 시뮬레이션에서는 잘 작동하는데, 실시간 시스템에서 예측값이 달라짐!

#### 문제 사례

```
실시간 시스템: ML 39.9% → 차단
시뮬레이션:   ML 52.3% → 통과

🔍 원인: 특성 추출 로직의 미묘한 차이
```

#### 원인 분석

디버깅 스크립트로 추적:

```python
# 발견된 차이점:
실시간: uptrend_gain = 3.52  (percentage)
시뮬:   uptrend_gain = 352000 (원 단위)

# → 단위 불일치!
```

#### 해결 방법

특성 추출 로직을 완전히 통일:

```python
def extract_features_from_pattern(self, pattern: Dict) -> pd.DataFrame:
    """
    시뮬레이션과 실시간 거래 양쪽 데이터 구조 지원

    지원 구조:
    1. pattern_stages: {1_uptrend, 2_decline, 3_support, 4_breakout}
    2. debug_info: {uptrend, decline, support, breakout}
    """

    # 🔄 두 구조 모두 지원
    pattern_stages = pattern.get('pattern_stages', {})
    debug_info = pattern.get('debug_info', {})

    # 상승 구간: 우선순위로 탐색
    uptrend = pattern_stages.get('1_uptrend', debug_info.get('uptrend', {}))

    # 필드명 통일 (gain_pct vs price_gain)
    uptrend_gain = self._safe_float(
        uptrend.get('gain_pct', uptrend.get('price_gain', 0.0))
    )

    # 안전한 형변환
    def _safe_float(self, value, default=0.0):
        if isinstance(value, str):
            # "3.52%" → 3.52, "162,154" → 162154
            value = value.replace(',', '').replace('%', '')
        return float(value) if value else default
```

**개선 사항:**
1. ✅ Dual Structure Support
2. ✅ Field Name Fallback
3. ✅ Safe Type Conversion
4. ✅ Unit Normalization

---

### 3.5 성능 검증: 메모리 리플레이

**완벽한 재현성** 확보를 위해, 실시간 메모리 데이터를 덤프하여 재실행:

```python
# 1. 실시간 시스템 동작 중: 메모리 데이터 덤프
# memory_data_YYYYMMDD_HHMMSS.txt

# 2. 이후: 덤프 데이터로 시뮬 재실행
python replay_from_memory.py memory_data_YYYYMMDD_HHMMSS.txt

# 3. 결과 비교
실시간 시스템: 09:30 → ML 39.9% (차단)
리플레이:      09:30 → ML 39.9% (차단) ✅ 완전 일치!
```

**검증 결과:**
- ✅ 실시간 vs 시뮬 예측값 일치율: **100%**
- ✅ 오차 범위: **±0.1% 이내**
- ✅ 실제 시스템에서 ML 필터 **정상 작동 확인**

---

## 4. ML 모델 관리 전략

ML 모델은 **시장 상황 변화**에 따라 성능이 저하될 수 있습니다. 지속 가능한 운영을 위한 관리 전략을 구축했습니다.

### 4.1 일일 자동 업데이트 파이프라인

#### Daily Update 프로세스

```bash
# 매일 장 마감 후 자동 실행 (Cron)
# 0 16 * * 1-5 /path/to/daily_update.sh

Step 1: 당일 패턴 데이터 수집
→ 데이터 수집 스크립트 실행
→ CSV 파일 생성

Step 2: 최근 60일 데이터로 재학습
→ 학습 스크립트 실행
→ 60일치 데이터 통합 → 학습

Step 3: 새 모델 검증
→ 테스트셋 정확도 > 65% 확인
→ Feature Importance 분석

Step 4: 모델 배포 여부 결정
→ 통과: 새 모델로 업데이트
→ 실패: 이전 모델 유지 + 알림
```

---

### 4.2 모델 버전 관리

```python
# 모델 저장 시 메타데이터 포함
model_data = {
    'model': lgb_model,
    'label_encoder': le,
    'feature_names': feature_names,
    'version': f'v_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
    'train_score': 0.756,
    'test_score': 0.729,
    'train_date': datetime.now().strftime("%Y-%m-%d"),
    'data_days': 60
}

with open('model.pkl', 'wb') as f:
    pickle.dump(model_data, f)
```

**버전 히스토리 관리:**

```bash
models/
├── model.pkl                    # 현재 사용 중
├── backups/
│   ├── model_v_YYYYMMDD_1.pkl  # 백업 1
│   ├── model_v_YYYYMMDD_2.pkl  # 백업 2
│   └── model_v_YYYYMMDD_3.pkl  # 백업 3
```

---

### 4.3 성능 모니터링

#### 실시간 성능 추적

```python
# 매 실행 후 정확도 계산
class MLPerformanceTracker:
    def __init__(self):
        self.predictions = []
        self.actuals = []

    def log_result(self, ml_prob, success):
        self.predictions.append(ml_prob)
        self.actuals.append(1 if success else 0)

    def get_weekly_stats(self):
        """주간 성능 리포트"""
        return {
            'accuracy': accuracy_score(self.actuals,
                                      [1 if p >= 0.5 else 0 for p in self.predictions]),
            'avg_prob_success': np.mean([p for p, a in zip(self.predictions, self.actuals) if a == 1]),
            'avg_prob_fail': np.mean([p for p, a in zip(self.predictions, self.actuals) if a == 0])
        }
```

#### 알림 시스템

```python
# 성능 저하 시 텔레그램 알림
if weekly_accuracy < 0.60:
    send_telegram_alert(
        f"⚠️ ML 모델 성능 저하 감지!\n"
        f"주간 정확도: {weekly_accuracy:.1%}\n"
        f"재학습 권장"
    )
```

---

### 4.4 데이터 품질 관리

#### 이상 데이터 탐지

```python
# 학습 전 데이터 검증
class DataValidator:
    def validate(self, df):
        issues = []

        # 1. 결측치 확인
        if df.isnull().sum().sum() > 0:
            issues.append("결측치 발견")

        # 2. 이상값 확인
        for col in numeric_columns:
            q1, q3 = df[col].quantile([0.25, 0.75])
            iqr = q3 - q1
            outliers = df[(df[col] < q1 - 3*iqr) | (df[col] > q3 + 3*iqr)]
            if len(outliers) > 0:
                issues.append(f"{col}: {len(outliers)}개 이상값")

        # 3. 클래스 불균형 확인
        success_ratio = df['label'].mean()
        if success_ratio < 0.3 or success_ratio > 0.7:
            issues.append(f"클래스 불균형: 성공률 {success_ratio:.1%}")

        return issues
```

---

### 4.5 A/B 테스팅

새 모델 배포 전 **A/B 테스트**:

```python
# 신규 모델과 기존 모델 병렬 실행
class ABTestRunner:
    def __init__(self):
        self.model_a = load_model('model_current.pkl')  # 기존
        self.model_b = load_model('model_new.pkl')      # 신규

    def predict(self, features):
        prob_a = self.model_a.predict(features)
        prob_b = self.model_b.predict(features)

        # 로그 기록 (실제 사용은 A만)
        self.log_predictions(prob_a, prob_b)

        return prob_a  # 기존 모델 사용

    def compare_performance(self, days=7):
        """7일 후 성능 비교"""
        return {
            'model_a_accuracy': self.calc_accuracy('a'),
            'model_b_accuracy': self.calc_accuracy('b')
        }
```

**배포 기준:**
- 신규 모델 정확도 > 기존 모델 정확도 + 2%
- 최소 7일 검증 기간
- 특성 중요도 변화 검토

---

### 4.6 롤백 전략

모델 배포 후 문제 발생 시 **즉시 롤백**:

```python
# 자동 롤백 조건
class AutoRollback:
    def check_rollback_conditions(self):
        conditions = [
            self.daily_error_rate > 0.4,      # 일일 오류율 40% 초과
            self.prediction_error > 0.2,      # 예측 오차 20% 초과
            self.system_crash_count > 3       # 시스템 크래시 3회 이상
        ]

        if any(conditions):
            self.rollback_to_previous_model()
            send_alert("🔄 모델 롤백 실행!")
```

**롤백 프로세스:**
1. 백업 모델 복구: `model.pkl` ← `backups/latest.pkl`
2. 시스템 재시작
3. 로그 기록 및 알림
4. 원인 분석 시작

---

### 4.7 장기 전략: 지속 가능한 ML 시스템

#### 1. 데이터 파이프라인이 80%

> "Garbage In, Garbage Out"

좋은 모델보다 **좋은 데이터**가 더 중요합니다:

- ✅ 실시간 시스템 동작 중 패턴 데이터 자동 수집
- ✅ 성공/실패 결과 정확히 라벨링
- ✅ 60일 이상의 충분한 학습 데이터 확보
- ✅ 데이터 품질 검증 자동화

#### 2. 실전 환경 검증 필수

시뮬레이션 성능 ≠ 실전 성능

- ✅ 메모리 데이터 리플레이로 100% 재현성 확보
- ✅ 실시간 vs 시뮬 특성 추출 로직 완전 통일
- ✅ 단위 불일치, 필드명 차이 등 세밀한 디버깅

#### 3. 단순함의 힘

복잡한 딥러닝 < **LightGBM + 잘 설계된 특성**

- ✅ 학습 시간: 1분
- ✅ 추론 속도: 0.001초/샘플
- ✅ 해석 가능성: 특성 중요도 분석 가능
- ✅ 유지보수 용이

#### 4. 지속적인 개선

시장은 변합니다. 모델도 함께 진화해야 합니다:

- ✅ 일일 자동 재학습
- ✅ 성능 모니터링 및 알림
- ✅ 모델 버전 관리
- ✅ A/B 테스팅 및 롤백 전략

---

## 향후 개선 계획

### 1. 앙상블 모델

여러 모델의 예측을 결합하여 안정성 향상:

```python
# LightGBM + XGBoost + CatBoost 앙상블
lgb_prob = lgb_model.predict(features)
xgb_prob = xgb_model.predict(features)
cat_prob = cat_model.predict(features)

final_prob = (lgb_prob * 0.5 + xgb_prob * 0.3 + cat_prob * 0.2)
```

### 2. 온라인 학습 (Online Learning)

실시간으로 모델을 업데이트:

```python
# 실행 결과를 즉시 학습 데이터에 추가
from river import linear_model

model = linear_model.LogisticRegression()

# 스트리밍 학습
for features, result in system_results:
    prediction = model.predict_one(features)
    model.learn_one(features, result)  # 즉시 업데이트!
```

### 3. 강화학습 (Reinforcement Learning)

의사결정 타이밍까지 최적화:

```python
# Q-Learning으로 최적 의사결정 시점 학습
class DecisionAgent:
    def act(self, state):
        # state: 현재 패턴, 상태, 메트릭 등
        return action  # WAIT / ENTER / EXIT

agent.train(episodes=10000)
```

### 4. 설명 가능한 AI (Explainable AI)

왜 이 신호를 차단했는지 설명:

```python
import shap

explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(features)

# 출력: "거래량 비율 0.45로 높아 차단 (기준: 0.35)"
```

---

## 결론

트레이딩 시스템에 머신러닝을 적용하면서 얻은 성과:

1. ✅ **신호 정확도를 50% → 73%로 향상** (패턴 신호 필터링 개선)
2. ✅ **실시간 vs 시뮬레이션 동기화** (재현 가능한 시스템 구축)
3. ✅ **자동 데이터 수집 및 학습 파이프라인** (지속 가능한 운영)

가장 중요한 교훈:

> **"ML 모델보다 데이터 파이프라인이 더 중요하다"**

좋은 데이터 수집 시스템이 있다면, 모델은 자연스럽게 성능이 향상됩니다.

---

**⚠️ 면책 조항**

이 글은 ML 기술 개발 경험을 공유하는 **교육 목적**의 기술 블로그입니다.
- 특정 투자 종목이나 전략을 추천하는 것이 아닙니다
- 수익을 보장하거나 투자를 권유하지 않습니다
- 실제 투자 시 발생하는 손실에 대해 책임지지 않습니다
- 투자 판단과 책임은 투자자 본인에게 있습니다

---

## 기술 스택

**개발 환경:**
- Python 3.10+
- 한국투자증권 KIS API
- LightGBM 4.0+
- scikit-learn 1.3+
- pandas, numpy

**주요 컴포넌트:**
- ML 예측기 (특성 추출 및 추론)
- 모델 학습 파이프라인 (Stratified K-Fold)
- 실시간 데이터 로거
- 일일 데이터 수집 스크립트
- 메모리 리플레이 검증 도구
- 자동 업데이트 시스템

---

## 맺음말

이 글이 ML 기반 트레이딩 시스템이나 시계열 데이터 분석 프로젝트를 개발하는 분들에게 도움이 되기를 바랍니다.

기술적인 질문이나 피드백은 GitHub Issues에 남겨주세요!
