# RoboTrader - 주식 단타 거래 시스템

한국투자증권 KIS API를 활용한 자동 주식 단타 거래 시스템입니다.

## 주요 기능

### 🔄 실시간 데이터 수집
- 30초/1분 주기로 OHLCV 데이터 수집
- 후보 종목들의 가격 변동 실시간 모니터링
- 비동기 처리로 다중 종목 동시 추적

### 📊 자동 매매 시스템
- 설정 가능한 매매 전략
- 실시간 매수/매도 신호 생성
- 자동 주문 실행 및 관리

### 🛡️ 리스크 관리
- 손절/익절 자동 실행
- 계좌 잔고 대비 투자 한도 관리
- 동시 보유 종목 수 제한

### 📋 주문 관리
- 미체결 주문 자동 모니터링
- 타임아웃 시 자동 취소
- 가격 변동 시 자동 정정

### 📱 텔레그램 모니터링
- 실시간 거래 상황 알림
- 주문 실행/체결 알림
- 매매 신호 감지 알림
- 원격 명령어 지원 (/status, /positions, /orders)

## 시스템 구조

```
RoboTrader/
├── api/                    # KIS API 연동
│   ├── kis_api_manager.py  # API 통합 관리자
│   ├── kis_auth.py         # 인증 관리
│   ├── kis_account_api.py  # 계좌 조회
│   ├── kis_market_api.py   # 시장 데이터
│   └── kis_order_api.py    # 주문 처리
├── core/                   # 핵심 비즈니스 로직
│   ├── models.py           # 데이터 모델
│   ├── data_collector.py   # 실시간 데이터 수집
│   └── order_manager.py    # 주문 관리
├── utils/                  # 유틸리티
│   ├── logger.py           # 로깅 시스템
│   ├── korean_time.py      # 한국 시간 처리
│   └── telegram/           # 텔레그램 모듈
│       └── telegram_notifier.py
├── config/                 # 설정 파일
│   ├── key.ini            # API 키 및 텔레그램 설정
│   └── trading_config.json # 거래 설정
├── docs/                   # 문서
│   └── telegram_setup.md   # 텔레그램 설정 가이드
├── main.py                # 메인 실행 파일
└── requirements.txt       # 의존성 패키지
```

## 설치 및 실행

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. API 키 및 텔레그램 설정
`config/key.ini` 파일에 다음을 설정하세요:
- 한국투자증권 API 키
- 텔레그램 봇 토큰 (선택사항)
- 텔레그램 Chat ID (선택사항)

상세한 텔레그램 설정은 `docs/telegram_setup.md` 참고

### 3. 거래 설정
`config/trading_config.json`에서 거래 설정을 조정하세요:
- 후보 종목 리스트
- 리스크 관리 설정
- 주문 관리 설정

### 4. 실행
```bash
python main.py
```

## 주요 클래스

### DayTradingBot
- 전체 시스템 관리
- 일일 거래 사이클 실행
- 비동기 태스크 관리

### RealTimeDataCollector
- 실시간 OHLCV 데이터 수집
- 후보 종목 관리
- 데이터 저장 및 제공

### OrderManager
- 주문 실행 및 관리
- 미체결 주문 모니터링
- 자동 정정/취소 처리

### KISAPIManager
- KIS API 통합 관리
- 인증 및 API 호출
- 오류 처리 및 재시도

## 안전 기능

### 🔒 리스크 제한
- 최대 투자 비율 제한
- 일일 최대 손실 한도
- 종목별 손절/익절 자동 실행

### 📡 모니터링
- 실시간 시스템 상태 로깅
- API 호출 통계 추적
- 주문 실행 내역 기록

### ⚠️ 오류 처리
- API 호출 실패 시 자동 재시도
- 네트워크 오류 대응
- 예외 상황 로깅

## 주의사항

1. **모의투자 환경에서 충분한 테스트 후 실투자 적용**
2. **API 호출 한도 준수 (분당 최대 호출 수 확인)**
3. **장중에만 실행 (09:00~15:30)**
4. **충분한 계좌 잔고 확보**

## 라이선스

이 프로젝트는 교육 및 연구 목적으로 제작되었습니다.
실제 투자에 사용 시 발생하는 손실에 대해 책임지지 않습니다.

## ML 학습 파이프라인

### 🤖 동적 손익비 ML 시스템

패턴별로 최적화된 손익비를 적용하고 ML 필터로 신호 품질을 향상시키는 시스템입니다.

#### 1단계: 패턴 로그 수집
```bash
python batch_signal_replay.py \
  -s 20250901 \
  -e 20251226 \
  -o test_results_dynamic \
  --save-pattern-log \
  --use-dynamic \
  --workers 8
```
- **결과물**:
  - `test_results_dynamic/`: 시뮬레이션 결과 (승/패 기록)
  - `pattern_data_log_dynamic/`: 4단계 패턴 상세 데이터 (JSONL 형식)

#### 2단계: ML 데이터셋 생성
```bash
python prepare_ml_dataset_dynamic.py
```
- **입력**: `test_results_dynamic/` + `pattern_data_log_dynamic/`
- **출력**: `ml_dataset_dynamic_pl.csv` (28개 특징 + 라벨)
- **특징**:
  - 패턴 특징 26개 (상승/하락/지지/돌파 구간 데이터)
  - 목표 손익비 2개 (`target_stop_loss`, `target_take_profit`)

#### 3단계: ML 모델 학습
```bash
python train_ml_dynamic_pl.py
```
- **알고리즘**: LightGBM
- **출력**:
  - `ml_model_dynamic_pl.pkl`: 학습된 모델
  - `ml_training_report_dynamic_pl.txt`: 성능 리포트

#### 4단계: 성능 검증
```bash
python batch_signal_replay_ml_dynamic.py \
  -s 20250901 \
  -e 20251226 \
  --workers 8
```
- 동적 손익비 + ML 필터 조합 성능 측정
- 결과: `signal_replay_log_ml_dynamic/`

---

### 📊 고정 손익비 ML 시스템 (기존)

고정된 3.5:2.5 손익비를 사용하며 ML 필터로 신호를 선별하는 시스템입니다.

#### 1단계: 패턴 로그 수집
```bash
python batch_signal_replay.py \
  -s 20250901 \
  -e 20251226 \
  -o signal_replay_log \
  --save-pattern-log \
  --workers 8
```
- **결과물**:
  - `signal_replay_log/`: 시뮬레이션 결과
  - `pattern_data_log/`: 패턴 상세 데이터

#### 2단계: ML 데이터셋 생성
```bash
python prepare_ml_dataset_fixed.py
```
- **입력**: `signal_replay_log/` + `pattern_data_log/`
- **출력**: `ml_dataset_fixed.csv` (26개 특징 + 라벨)
- **특징**: 패턴 특징만 26개 (목표 손익비 없음 - 항상 고정 3.5:2.5)

#### 3단계: ML 모델 학습
```bash
python train_ml_merged.py
# 또는
python train_ml_experiments.py
```
- **출력**: `ml_model.pkl`

#### 4단계: 성능 검증
```bash
python apply_ml_filter.py \
  signal_replay_log/signal_new2_replay_20250901_9_00_0.txt \
  --model ml_model.pkl \
  --threshold 0.5
```

---

### 📁 데이터 폴더 구조

```
RoboTrader/
├── pattern_data_log/              # 고정 손익비 패턴 로그
│   └── pattern_data_YYYYMMDD.jsonl
├── pattern_data_log_dynamic/      # 동적 손익비 패턴 로그
│   └── pattern_data_YYYYMMDD.jsonl
├── signal_replay_log/             # 고정 손익비 시뮬 결과
│   └── signal_new2_replay_*.txt
├── test_results_dynamic/          # 동적 손익비 시뮬 결과
│   └── signal_new2_replay_*.txt
├── ml_dataset_dynamic_pl.csv      # 동적 ML 데이터셋
├── ml_model_dynamic_pl.pkl        # 동적 ML 모델
└── ml_model.pkl                   # 고정 ML 모델
```

---

## 개발 계획

- [ ] 다양한 매매 전략 플러그인
- [ ] 웹 대시보드 구현
- [x] 백테스팅 기능
- [x] 텔레그램 알림 연동
- [x] 딥러닝 기반 예측 모델 (LightGBM ML 필터)