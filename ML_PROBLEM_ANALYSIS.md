# ML 모델 근본 문제 분석 및 해결 방안

**분석일**: 2025-11-21
**결론**: V1, V2 모두 심각한 과적합과 데이터 분할 문제 존재

---

## 🚨 발견된 문제

### 1. 심각한 과적합 (Overfitting)

| 모델 | 교차검증 AUC | 테스트 AUC | 차이 |
|------|-------------|-----------|------|
| V1 | **99.26%** | 54.90% | **-44.36%p** |
| V2 | **99.09%** | 50.21% | **-48.88%p** |

**두 모델 모두 학습 데이터에 과적합되어 새로운 데이터에서 성능이 급락합니다.**

### 2. 치명적인 데이터 분할 문제

#### 현재 방식: 시간 기반 분할 (60% / 20% / 20%)

```python
# ml_train_model.py
train_split = int(len(X) * 0.6)
val_split = int(len(X) * 0.8)

X_train = X.iloc[:train_split]      # 앞 60%: 9월 초~중순
X_val = X.iloc[train_split:val_split]  # 중간 20%: 9월 말~10월 초
X_test = X.iloc[val_split:]         # 뒤 20%: 10월 중~11월
```

#### 문제점: 시기별 승률이 다름

```
학습 세트 (9월 초~중): 승률 54.4% ✅
검증 세트 (9월 말~10월 초): 승률 49.2%
테스트 세트 (10월 중~11월): 승률 37.0% ⚠️⚠️⚠️
```

**시간이 지날수록 패턴의 효과가 감소하고 있습니다.**

원인:
- 시장 환경 변화 (9월: 상승장 → 10-11월: 조정장?)
- 패턴 자체의 시효성 문제
- 학습 데이터와 테스트 데이터의 분포가 다름 (Distribution Shift)

#### 시간대 분포도 불균형

```
학습 세트: hour=0 (1,083건), hour=19 (982건) 多
테스트 세트: hour=0 (584건), hour=1 (7건) 少
```

---

## 🔍 왜 실전 백테스트는 좋았나?

**실전 백테스트 결과 (V1 모델)**:
- 승률: 54.8%
- 평균 수익률: 0.59%
- 총 수익률: 235.88%

### 이유: 같은 시기 데이터

```
학습: pattern_data_log (9월 데이터 포함)
백테스트: signal_replay_log (9월 데이터)
```

**9월 데이터로 학습하여 9월 데이터를 테스트** → 당연히 잘 맞음

하지만 최근 데이터(10-11월)에서는 성능 급락!

---

## 💡 해결 방안

### 방안 1: Stratified K-Fold (권장) ⭐

시간 순서를 무시하고 라벨 분포를 유지하며 무작위 분할

**장점**:
- 각 fold의 승률이 균등 (~50%)
- 과적합 방지
- 일반화 성능 향상

**단점**:
- 미래 데이터로 과거 예측하는 data leakage 가능성
- 하지만 패턴은 시점 독립적이므로 문제 없을 것

**구현**:
```python
from sklearn.model_selection import StratifiedKFold

# 전체 데이터를 라벨 비율 유지하며 분할
splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

for train_idx, test_idx in splitter.split(X, y):
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
```

### 방안 2: 더 긴 시간 범위 데이터 수집

현재: 9월 1일 ~ 11월 18일 (약 2.5개월)

**확장**:
- 6개월 이상 데이터 수집
- 다양한 시장 환경 포함 (상승장, 하락장, 횡보장)

**장점**:
- 시장 환경 변화에 강인한 모델
- 시간 기반 분할 시에도 안정적

**구현**:
```python
# 6개월 전부터 데이터 수집
python save_daily_data_for_ml.py --start 20250601
```

### 방안 3: Walk-Forward Validation

시계열 데이터에 적합한 검증 방법

**개념**:
```
Fold 1: Train[1-3월] → Test[4월]
Fold 2: Train[1-4월] → Test[5월]
Fold 3: Train[1-5월] → Test[6월]
...
```

**장점**:
- 실전과 동일한 방식 (과거로 미래 예측)
- Data leakage 없음

**단점**:
- 구현 복잡
- 초기 데이터가 적으면 학습 부족

### 방안 4: 정규화 강화 + 특성 선택

과적합을 줄이는 근본적 방법

**A. 정규화 파라미터 조정**:
```python
params = {
    'num_leaves': 15,           # 31 → 15 (복잡도 감소)
    'max_depth': 4,             # 6 → 4
    'min_data_in_leaf': 50,     # 20 → 50
    'lambda_l1': 1.0,           # 0.5 → 1.0
    'lambda_l2': 1.0,           # 0.5 → 1.0
    'learning_rate': 0.01,      # 0.03 → 0.01
}
```

**B. 특성 선택**:
- V1: 26개 → 15개로 축소 (중요도 낮은 것 제거)
- V2: 62개 → 25개로 축소 (중요도 0인 23개 + 낮은 것 제거)

**C. Dropout 비율 증가**:
```python
'feature_fraction': 0.6,  # 0.8 → 0.6
'bagging_fraction': 0.6,  # 0.8 → 0.6
```

### 방안 5: 앙상블 + Calibration

예측 확률 보정

```python
from sklearn.calibration import CalibratedClassifierCV

# 확률 보정
calibrated_model = CalibratedClassifierCV(lgb_model, cv=5, method='isotonic')
calibrated_model.fit(X_train, y_train)
```

---

## 🎯 권장 조치 순서

### 1단계: 즉시 (Stratified 분할로 재학습) ⭐

```bash
# ml_train_model_stratified.py 생성
# Stratified K-Fold로 데이터 분할
# 정규화 강화
python ml_train_model_stratified.py
```

**예상 결과**:
- 교차검증 AUC: 70-80% (현재 99%보다 낮지만 현실적)
- 테스트 AUC: 60-70% (현재 55%보다 향상)
- 과적합 감소

### 2단계: 중기 (데이터 확장)

```bash
# 6개월 이상 데이터 수집
# 다양한 시장 환경 포함
```

### 3단계: 장기 (Walk-Forward + 앙상블)

고급 기법 적용

---

## 📊 기대 효과

| 방안 | 예상 테스트 AUC | 과적합 감소 | 구현 난이도 |
|------|----------------|------------|-----------|
| 현재 | 0.55 | - | - |
| Stratified 분할 | **0.65-0.70** | ⭐⭐⭐ | ⭐ |
| 데이터 확장 | 0.60-0.65 | ⭐⭐ | ⭐⭐ |
| Walk-Forward | 0.60-0.65 | ⭐⭐⭐ | ⭐⭐⭐ |
| 정규화 강화 | 0.60-0.65 | ⭐⭐⭐ | ⭐ |
| **조합 (1+4)** | **0.70-0.75** | ⭐⭐⭐⭐ | ⭐⭐ |

---

## 🔬 검증 방법

재학습 후 다음을 확인:

1. **과적합 체크**: 교차검증 AUC와 테스트 AUC 차이 < 10%p
2. **승률 분포**: 학습/검증/테스트 승률 차이 < 5%p
3. **실전 성능**: 최근 1개월 데이터로 백테스트 (승률 > 50%)

---

## 📁 다음 작업

**즉시 실행 가능**:

```bash
# 1. Stratified 분할 모델 생성
python create_stratified_model.py

# 2. 재학습
python ml_train_model_stratified.py

# 3. 최근 데이터로 백테스트
python batch_signal_replay_ml.py --start 20251101 --end 20251118
```

---

## 결론

**현재 모델(V1, V2)은 실전 투자에 사용 불가합니다.**

- 과적합으로 인해 새로운 시기 데이터에서 성능 급락
- 9월 데이터 백테스트만 좋았을 뿐, 실제 미래 예측 불가
- **Stratified 분할 + 정규화 강화**로 재학습 필수

**우선순위**:
1. ⭐ Stratified 분할로 재학습 (즉시)
2. 데이터 확장 (중기)
3. Walk-Forward 검증 (장기)
