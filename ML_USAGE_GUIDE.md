# 🤖 ML 필터 시스템 사용 가이드

## 📋 개요
이제 두 가지 버전의 신호 리플레이 시스템을 사용할 수 있습니다:

### 🔄 기본 버전 (signal_replay.py)
- 기술적 분석만 사용
- 모든 신호를 그대로 처리
- 빠른 실행 속도

### 🤖 ML 강화 버전 (signal_replay_ml.py)
- 기술적 분석 + ML 예측 필터
- 낮은 승률 신호 자동 차단
- 더 정확한 신호 선별

## 🚀 실행 방법

### 단일 날짜 테스트
```bash
# 기본 버전
python utils/signal_replay.py --date 20250912 --export txt

# ML 버전
python utils/signal_replay_ml.py --date 20250912 --export txt
```

### 배치 실행 (당신이 사용하는 방법)
```bash
# 기본 버전 (기존 방식)
python batch_signal_replay.py -s 20250901 -e 20250912

# ML 버전 (새로운 방식)
python batch_signal_replay_ml.py -s 20250901 -e 20250912
```

## 📊 결과 파일 구분

### 기본 버전 출력
```
signal_replay_log/signal_new2_replay_20250912_9_0_0.txt
```

### ML 버전 출력
```
signal_replay_log/signal_ml_replay_20250912_9_0_0.txt
```

## 🔍 ML 필터링 동작 원리

ML 시스템이 각 매수 신호를 평가하여:

1. **승률 ≥ 80%**: 🟢 STRONG_BUY (무조건 승인)
2. **승률 ≥ 65%**: 🟢 BUY (승인)
3. **승률 ≥ 55%**: 🟡 WEAK_BUY (조건부 승인)
4. **승률 < 55%**: 🚫 SKIP (차단)

## 📈 성능 비교 방법

동일한 기간에 대해 두 버전을 실행하여 비교:

```bash
# 1단계: 기본 버전 실행
python batch_signal_replay.py -s 20250901 -e 20250912

# 2단계: ML 버전 실행
python batch_signal_replay_ml.py -s 20250901 -e 20250912

# 3단계: 결과 비교
# signal_new2_replay_*.txt (기본)
# signal_ml_replay_*.txt (ML)
```

## 💡 권장 사용법

### 백테스팅용
- **ML 버전 사용 권장**: 더 정확한 신호로 실제 성과 예측

### 빠른 분석용
- **기본 버전 사용**: 신속한 패턴 확인

### 실전 적용 전
- **두 버전 모두 실행**: 성능 차이 확인 후 결정

## ⚠️ 주의사항

1. **ML 모델 파일 필요**: `trade_analysis/ml_models/*.pkl`
2. **첫 실행 시간**: ML 모델 로딩으로 약간 더 오래 걸림
3. **메모리 사용량**: ML 버전이 더 많은 메모리 사용

## 🔧 트러블슈팅

### ML 모델이 없는 경우
```
⚠️ ML 모델 파일이 없습니다 - 기본 신호만 사용됩니다
```
→ `python trade_analysis/run_ml_training.py`로 모델 학습

### 실행 오류 발생 시
```bash
# ML 시스템 테스트
python test_ml_integration.py

# 기본 버전으로 대체
python batch_signal_replay.py -s 날짜 -e 날짜
```

이제 ML 필터가 적용된 더 정교한 신호 분석이 가능합니다! 🎯