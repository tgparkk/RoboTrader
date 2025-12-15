"""
ML 시스템 설정

현재 사용 중인 ML 모델: ml_model.pkl (26개 패턴 특성)
- 학습 데이터: 11월 패턴 데이터
- 성능: 승률 52.1%, 거래당 평균 +7,238원
- 다음 재학습 예정: 2025년 1월 초 (12월 데이터 포함)
"""

class MLSettings:
    """ML 관련 설정"""

    # ML 필터 사용 여부
    USE_ML_FILTER = True  # ML 필터 활성화

    # ML 모델 파일
    MODEL_PATH = "ml_model.pkl"  # 현재 사용 중인 모델

    # ML 필터링 임계값 (승률 예측값 기준)
    ML_THRESHOLD = 0.5  # 50% 이상 승률 예측 시 매수 허용

    # 에러 발생 시 동작
    ON_ML_ERROR_PASS_SIGNAL = True  # True: 신호 통과, False: 신호 차단