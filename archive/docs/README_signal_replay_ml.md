# 🤖 ML 필터 적용된 Signal Replay 사용법

## 📋 개요

`signal_replay_ml.py`는 기존 `signal_replay.py`에 ML 예측 필터를 추가한 버전입니다. 매수 신호 발생 시 ML 모델의 승률 예측을 통해 신호를 필터링합니다.

## 🆚 기존 버전과의 차이점

### ❌ signal_replay.py (기본)
- 기술적 분석만으로 신호 생성
- 모든 매수 신호를 그대로 처리
- 파일명: `signal_new2_replay_20250901_9_0_0.txt`

### ✅ signal_replay_ml.py (ML 강화)
- 기술적 분석 + ML 예측 필터링
- 승률이 낮은 신호는 자동 차단
- ML 예측 결과가 로그에 표시
- 파일명: `signal_ml_replay_20250901_9_0_0.txt`

## 🚀 사용 방법

### 1. 단일 날짜 실행
```bash
python utils/signal_replay_ml.py --date 20250912 --export txt
```

### 2. 배치 실행 (기간 지정)
```bash
python batch_signal_replay_ml.py -s 20250901 -e 20250912
```

### 3. 특정 종목만 테스트
```bash
python utils/signal_replay_ml.py --date 20250912 --codes 381620,054540 --export txt
```

## 📊 출력 결과 예시

### ML 승인된 신호
```
[09:33] 종가:12,160 거래량:125,000 🟢강매수 신뢰도:85% 🤖ML승인:BUY(승률92.6%)
```

### ML 차단된 신호
```
[10:15] 종가:11,800 거래량:89,000 🚫ML차단(STRONG_BUY) 차단사유:ML차단:SKIP(승률42.1%)
```

### ML 조건부 승인
```
[11:42] 종가:12,350 거래량:156,000 🟡조건부매수 신뢰도:78% 🤖ML조건부승인(승률68.3%)
```

## 🔧 ML 필터 동작 원리

### 필터링 조건
1. **STRONG_BUY**: 무조건 승인 (승률 ≥ 80%)
2. **BUY**: 승인 (승률 ≥ 65%)  
3. **WEAK_BUY**: 조건부 승인 (승률 ≥ 55%)
4. **SKIP**: 차단 (승률 < 55%)

### 예측 과정
1. 기술적 분석으로 기본 신호 생성
2. ML 모델이 해당 시점의 데이터로 승률/수익률 예측
3. 예측 결과에 따라 신호 승인/차단 결정
4. 최종 결과를 로그에 상세 표시

## 📈 성능 비교

### 예상되는 개선 효과
- **승률 향상**: 낮은 확률 신호 차단으로 전체 승률 상승
- **위험 감소**: ML이 위험 신호를 사전 차단
- **선택적 거래**: 고확률 신호만 선별적 거래

### 성능 측정 방법
```bash
# 1. 기본 버전 실행
python batch_signal_replay.py -s 20250901 -e 20250912

# 2. ML 버전 실행  
python batch_signal_replay_ml.py -s 20250901 -e 20250912

# 3. 결과 파일 비교
# signal_new2_replay_*.txt (기본)
# signal_ml_replay_*.txt (ML 강화)
```

## ⚙️ 설정 옵션

### ML 필터 임계값 조정
`utils/signal_replay_ml.py`에서:
```python
# 필터링 조건 수정 (153-158라인)
if action in ['STRONG_BUY', 'BUY']:
    return True, f"ML승인:{action}(승률{win_probability:.1%})", ml_result
elif action == 'WEAK_BUY' and win_probability >= 0.55:  # 임계값 조정
    return True, f"ML조건부승인(승률{win_probability:.1%})", ml_result
```

### ML 필터 비활성화
ML 모델 파일이 없으면 자동으로 기본 신호만 사용:
```
⚠️ ML 모델 파일이 없습니다 - 기본 신호만 사용됩니다
```

## 🚨 주의사항

1. **ML 모델 필수**: `trade_analysis/ml_models/*.pkl` 파일 필요
2. **학습 데이터**: 충분한 학습 데이터로 모델이 학습되어야 함
3. **성능 검증**: 백테스팅 결과를 실전에 적용하기 전 충분히 검증
4. **시장 변화**: 시장 상황 변화 시 모델 재학습 필요

## 🔄 업데이트 방법

### ML 모델 재학습
```bash
python trade_analysis/run_ml_training.py --start-date 20250901 --end-date 20250912
```

### 최신 데이터로 성능 테스트
```bash
python batch_signal_replay_ml.py -s 20250910 -e 20250912
```

## 📞 문의사항

ML 필터 관련 문제가 있으면 로그 파일을 확인하거나 다음 명령으로 ML 시스템을 테스트하세요:
```bash
python test_ml_integration.py
```