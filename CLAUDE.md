-눌림목 캔들패턴-

주가는 상승, 거래량의 추세는 하락, 주가가 이등분선 위에서 조정받는 동안 거래량이 급감하며 봉 캔들이 짧아졌다. 이후 급감되었던 거래량이 조금씩 증가하며 봉의 크키가 서서히 커진다 -> 매수



(본래 주가가 상승할수록 거래량 증가가 일반적이지만, 주가가 상승할수록 거래량이 하락추세면 매물의 부담이 없다는것. 적은 돈으로 주가가 올랐기 때문에 하락할 때도 적은 돈으로 하락할 가능성 높음. 즉, 대량의 매도물량이 나오지 않을 가능성이 높아 매물부담 없이 눌림목에서 반등 확률 높음)



'급감된 거래량' 을 다음 봉에서 상회를 했고 캔들의 크기가 커졌는지 판단.

손절 타이밍

'이등분선 이탈' 또는 지지가 되었던 저점을 이탈할 때.



이등분선을 이탈해도 , 지지되다가 이등분선을 넘어서면서 거래량이 조금씩 증가 -> 매수



당일 분봉차트(3분봉) 에서 가장 많이 나온 거래량을 기준거래량으로 설정하고 이 기준 거래량의 1/2 수치 정도 거래되면서 주가가 하락한다면 매도세가 쏟아진다고 판단가능. 이 매도세는 결국 악성매물로 바뀌게 되어 주가 상승 방해.



통상적으로 기준 거래량의 1/4 수준으로 거래돼야 상대적으로 매물부담이 덜함.

---

# RoboTrader 시스템 분석 방법

## 실시간 거래 분석
- **로그 파일**: `logs/trading_YYYYMMDD.log`
- **종목 선정 시점**: `grep "종목코드" logs/trading_YYYYMMDD.log | grep "선정 완료"`
- **매수 신호**: `grep "종목코드" logs/trading_YYYYMMDD.log | grep "매수 신호 발생"`
- **ML 필터 결과**: `grep "종목코드" logs/trading_YYYYMMDD.log | grep "ML 필터"`
- **패턴 상세 정보**: `pattern_data_log/pattern_data_YYYYMMDD.jsonl`

## 시뮬레이션 분석
- **순수 패턴 신호**: `signal_replay_log/signal_new2_replay_YYYYMMDD_9_00_0.txt`
- **ML 필터 적용**: `signal_replay_log_ml/signal_ml_replay_YYYYMMDD_9_00_0.txt`
- **데이터 소스**: `cache/minute_data/종목코드_YYYYMMDD.pkl` (확정된 캐시 데이터)
- **주의**: selection_date 필터링 적용됨 (선정 시점 이전 신호는 차단)

## 실시간 vs 시뮬 차이 분석 3단계
1. **신호 시점 비교**: 실시간과 시뮬에서 같은 시간에 신호가 발생했는가?
2. **selection_date 확인**: 시뮬에서 필터링되었는가? (completion_time < selection_date 체크)
3. **데이터 일치 확인**: 캐시 데이터 vs 실시간 패턴 로그 데이터 비교

## 핵심 개념
- **3분봉 completion_time**: 라벨 시간 + 3분 (예: 10:42 캔들 → 10:45:00 완성)
- **ML 임계값**: 50% (config/ml_settings.py의 ML_THRESHOLD)
- **selection_date 필터링**: 시뮬레이션에서만 적용 (실시간은 없음)
- **데이터 차이**: 실시간은 지속 업데이트, 캐시는 확정값 → 같은 시간대 캔들도 값이 다를 수 있음

## 주요 차이 원인
1. **selection_date 필터링**: 시뮬에서 선정 시점 이전 신호 차단
2. **데이터 불일치**: 실시간 업데이트 데이터 vs 확정 캐시 데이터
3. **ML 확률 차이**: 패턴 구조가 미묘하게 다를 경우

상세 가이드: `ROBOTRADER_ANALYSIS_GUIDE.md` 참조

## ML 모델 관련

- 현재 사용 중: ml_model.pkl (config/ml_settings.py)
- ml_model_merged.pkl은 AUC 0.75로 높지만, 실전에서는 ml_model.pkl이 더 우수
- 실제 성능: 승률 52.1%, 거래당 평균 +7,238원

---

## 데이터 캐시 시스템 (2026-01-18 업데이트)

### DuckDB 마이그레이션 완료
- **기존**: pkl 파일 기반 캐시 (cache/minute_data/*.pkl, cache/daily/*.pkl)
- **현재**: DuckDB 기반 캐시 (`cache/market_data_v2.duckdb`)

### 테이블 구조
- **분봉 데이터**: `minute_{종목코드}` 테이블 (예: `minute_005930`)
- **일봉 데이터**: `daily_{종목코드}` 테이블 (예: `daily_005930`)
- 약 750개 분봉 테이블, 747개 일봉 테이블

### 주요 클래스
- `DataCache` (utils/data_cache.py): 분봉 데이터 캐시 관리
- `DailyDataCache` (utils/data_cache.py): 일봉 데이터 캐시 관리

### 데이터 로드 우선순위
1. DuckDB에서 로드 시도
2. DuckDB에 없으면 pkl 파일에서 폴백 로드 (하위 호환성)

### gitignore 처리
- `cache/daily/`, `cache/minute_data/`, `cache/*.duckdb` - git 추적 제외
- `signal_replay_log/`, `signal_replay_log_ml/` - git 추적 제외