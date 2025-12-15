# RoboTrader ML 시스템

## 📊 현재 사용 중인 모델

**모델 파일**: `ml_model.pkl`

**모델 정보**:
- 학습 날짜: 2024년 12월 1일
- 특성 수: 26개 (패턴 특성만)
- 학습 데이터: 11월 패턴 데이터 (약 749개 샘플)

**성능 (12/1~12/8 백테스트)**:
- 총 거래: 48개 (ML 필터 통과)
- 승률: 52.1%
- 총 수익률: +34.74%
- 거래당 평균 수익: +7,238원
- 손익비: 1.58:1

**비교 (ML 미적용)**:
- 총 거래: 89개
- 승률: 52.8%
- 총 수익률: +62.37%
- 거래당 평균 수익: +7,008원

**현재 상태**: ML 필터가 거래 수를 줄이지만, 거래당 수익은 비슷한 수준

---

## 🎯 ML 시스템 구조

### 1. 핵심 파일

**모델 & 데이터**:
- `ml_model.pkl` - 현재 사용 중인 ML 모델
- `ml_dataset.csv` - 학습 데이터셋

**학습 파이프라인**:
- `ml_prepare_dataset.py` - 패턴 로그에서 학습 데이터셋 생성
- `ml_train_model.py` - 모델 학습 스크립트

**실시간 운영**:
- `core/ml_predictor.py` - 실시간 ML 예측기
- `core/trading_decision_engine.py` - ML 필터 적용 (258번 라인)

**백테스트**:
- `apply_ml_filter.py` - 신호에 ML 필터 적용
- `batch_signal_replay_ml.py` - ML 필터 적용 백테스트
- `batch_apply_ml_filter.py` - 배치 ML 필터링

**설정**:
- `config/ml_settings.py` - ML 시스템 설정

### 2. 사용하는 특성 (26개)

**시간 특성 (4개)**:
- hour, minute, time_in_minutes, is_morning

**신호 특성 (2개)**:
- signal_type, confidence

**상승구간 특성 (5개)**:
- uptrend_candles, uptrend_gain, uptrend_max_volume
- uptrend_avg_body, uptrend_total_volume

**하락구간 특성 (3개)**:
- decline_candles, decline_pct, decline_avg_volume

**지지구간 특성 (4개)**:
- support_candles, support_volatility
- support_avg_volume_ratio, support_avg_volume

**돌파양봉 특성 (3개)**:
- breakout_volume, breakout_body, breakout_range

**비율 특성 (5개)**:
- volume_ratio_decline_to_uptrend
- volume_ratio_support_to_uptrend
- volume_ratio_breakout_to_uptrend
- price_gain_to_decline_ratio
- candle_ratio_support_to_decline

**참고**: 일봉 데이터(RSI, MACD, 볼린저밴드 등)는 현재 사용하지 않음

---

## 🔄 재학습 방법

### 1. 데이터셋 생성

```bash
python ml_prepare_dataset.py
```

**입력**: `pattern_data_log/*.jsonl` (패턴 데이터 로그)
**출력**: `ml_dataset.csv` (학습용 데이터셋)

### 2. 모델 학습

```bash
python ml_train_model.py
```

**입력**: `ml_dataset.csv`
**출력**: `ml_model.pkl` (학습된 모델)

### 3. 백테스트

```bash
# 특정 기간 백테스트
python batch_signal_replay_ml.py --start 20251201 --end 20251215

# 전체 기간 백테스트
python batch_signal_replay_ml.py
```

**결과 위치**: `signal_replay_log_ml/`

---

## 📅 재학습 일정

### 다음 재학습 예정

**시기**: 2025년 1월 초

**이유**:
1. 12월 말까지 데이터 수집 (현재 12/1~12/15, 약 10거래일)
2. 12월 전체 데이터 확보 (약 20거래일)
3. 더 많은 샘플로 ML 성능 향상 가능
4. 데이터 신선도 유지 (1~2개월 데이터가 최적)

### 재학습 체크리스트

- [ ] 12월 31일 이후 데이터 수집 완료 확인
- [ ] `pattern_data_log/` 디렉토리에 12월 데이터 존재 확인
- [ ] `python ml_prepare_dataset.py` 실행
- [ ] `python ml_train_model.py` 실행
- [ ] `python batch_signal_replay_ml.py` 로 성능 검증
- [ ] 성능이 향상되었다면 새 모델 적용
- [ ] 성능이 비슷하거나 나빠졌다면 기존 모델 유지

---

## ⚙️ 설정

**파일**: `config/ml_settings.py`

**주요 설정**:
- `USE_ML_FILTER = True` - ML 필터 활성화/비활성화
- `MODEL_PATH = "ml_model.pkl"` - 사용할 모델 파일
- `ML_THRESHOLD = 0.5` - 승률 임계값 (50% 이상 예측 시 매수 허용)
- `ON_ML_ERROR_PASS_SIGNAL = True` - 에러 발생 시 신호 통과 여부

**임계값 조정**:
- `0.3~0.4`: 공격적 (더 많은 거래, 낮은 승률)
- `0.5`: 중립 (현재 설정)
- `0.6~0.7`: 보수적 (적은 거래, 높은 승률)

---

## 📦 아카이브된 파일

**위치**: `archive/`

**모델**:
- `ml_models/ml_model_stratified.pkl` - Stratified 방식 모델 (미사용)
- `ml_models/ml_model_v2.pkl` - 일봉 데이터 포함 모델 (미사용)

**스크립트**:
- `ml_scripts/ml_train_model_v2.py` - V2 모델 학습 스크립트
- `ml_scripts/ml_train_model_stratified.py` - Stratified 모델 학습 스크립트
- `ml_scripts/ml_prepare_dataset_v2.py` - V2 데이터셋 준비 (일봉 포함)

**테스트**:
- `ml_tests/` - 각종 테스트 및 검증 스크립트

**분석**:
- `ml_analysis/` - ML 성능 비교 및 분석 스크립트

**문서**:
- `ml_docs/ML_STRATIFIED_SUCCESS.md` - Stratified 모델 성공 리포트
- `ml_docs/blog_ml_journey.md` - ML 개발 과정 블로그

---

## 🚨 문제 해결

### ML 필터가 너무 많은 신호를 차단하는 경우

1. **임계값 낮추기**:
   ```python
   # config/ml_settings.py
   ML_THRESHOLD = 0.3  # 0.5 → 0.3으로 낮춤
   ```

2. **ML 필터 일시 비활성화**:
   ```python
   # config/ml_settings.py
   USE_ML_FILTER = False
   ```

### ML 모델 로드 실패

1. `ml_model.pkl` 파일 존재 확인
2. 파일 크기 확인 (약 300KB)
3. 재학습 실행: `python ml_train_model.py`

### 성능이 나빠진 경우

1. 기존 모델 백업:
   ```bash
   cp ml_model.pkl ml_model_backup_YYYYMMDD.pkl
   ```

2. 재학습 실행

3. 백테스트로 비교:
   ```bash
   python batch_signal_replay_ml.py
   ```

4. 성능이 더 나쁘다면 백업 모델로 복원:
   ```bash
   cp ml_model_backup_YYYYMMDD.pkl ml_model.pkl
   ```

---

## 📚 참고 자료

**패턴 데이터 수집**:
- `core/pattern_data_logger.py` - 패턴 데이터 로깅
- `pattern_data_log/` - 로그 저장 위치

**신호 리플레이**:
- `utils/signal_replay.py` - 일반 신호 리플레이
- `utils/signal_replay_ml.py` - ML 필터 적용 신호 리플레이

**통계**:
- `signal_replay_log/` - ML 미적용 백테스트 결과
- `signal_replay_log_ml/` - ML 적용 백테스트 결과

---

**작성일**: 2024-12-15
**작성자**: Claude Code
**버전**: 1.0
