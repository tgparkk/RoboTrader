# 실시간 거래 vs 시뮬레이션 검증 가이드

## 📋 목차
1. [개요](#개요)
2. [핵심 차이점](#핵심-차이점)
3. [검증 도구](#검증-도구)
4. [검증 프로세스](#검증-프로세스)
5. [문제 해결](#문제-해결)

---

## 개요

### 목적
- 실시간 거래에서 수집한 분봉 데이터가 정확한지 검증
- 시뮬레이션 결과와 비교하여 로직 일치성 확인
- 데이터 품질 문제 조기 발견

### 핵심 질문
1. ✅ 실시간 분봉 데이터 = 시뮬 분봉 데이터?
2. ✅ 동일 데이터 → 동일 신호?
3. ⚠️ 동일 신호 → 동일 수익률? (매도가 차이로 0.1~1.0% 차이 허용)

---

## 핵심 차이점

### 1. 데이터 수집 방식

| 항목 | 실시간 | 시뮬레이션 | 일치 여부 |
|------|--------|-----------|----------|
| 수집 시점 | 선정 시 + 장중 매분 | 장 마감 후 일괄 | ⚠️ 다름 |
| 데이터 소스 | 2개 (historical + realtime) | 1개 (전체) | ⚠️ 다름 |
| 병합 필요 | ✅ 필요 | ❌ 불필요 | ⚠️ 다름 |
| 중복 가능성 | ⚠️ 있음 (해결됨) | ✅ 없음 | ✅ 해결 |
| 누락 가능성 | ⚠️ 있음 (2개 수집으로 보완) | ✅ 없음 | ✅ 보완 |

**결론**: 15:30 자동 저장 시 완전한 데이터 확보 → 일치성 보장

### 2. 로직 차이

| 항목 | 실시간 | 시뮬레이션 | 일치 여부 |
|------|--------|-----------|----------|
| 3분봉 변환 | `TimeFrameConverter.convert_to_3min_data()` | 동일 함수 | ✅ 일치 |
| 신호 생성 | `PullbackCandlePattern.generate_improved_signals()` | 동일 함수 | ✅ 일치 |
| 매수 가격 | 4/5가 계산 | 4/5가 계산 | ✅ 일치 |
| 손익비 | `trading_config.json` | `trading_config.json` | ✅ 일치 |
| 매도 기준 | 현재가 API | 1분봉 고가/저가 | ⚠️ 다름 |

**결론**: 신호는 100% 일치, 매도가만 0.1~1.0% 차이 (허용)

---

## 검증 도구

### 1. `compare_realtime_vs_simulation_data.py`
**목적**: 분봉 데이터 비교

**사용법**:
```bash
# 전체 종목 비교
python compare_realtime_vs_simulation_data.py --date 20251013

# 특정 종목만
python compare_realtime_vs_simulation_data.py --stock 003160 --date 20251013
```

**출력**:
- 행 개수 일치 여부
- 컬럼 일치 여부
- OHLCV 데이터 일치 여부
- 최대 차이값

### 2. `verify_realtime_simulation_consistency.py`
**목적**: 신호 생성 일치성 검증

**사용법**:
```bash
python verify_realtime_simulation_consistency.py --stock 003160 --date 20251013
```

**출력**:
- 3분봉 변환 일치성
- 신호 생성 5회 반복 일치성
- 매수 로직 상세 비교

### 3. `detailed_logic_comparison.py`
**목적**: 로직 단계별 상세 비교

**사용법**:
```bash
python detailed_logic_comparison.py --stock 003160 --date 20251013
```

**출력**:
- 각 단계별 상세 결과
- 신호 발생 시점별 분석
- 중복 신호 차단 확인
- 손익비 설정 확인

### 4. `auto_verify_consistency.py`
**목적**: 자동 품질 검증

**사용법**:
```bash
# 오늘 데이터 자동 검증
python auto_verify_consistency.py

# 특정 날짜 검증 + 리포트 생성
python auto_verify_consistency.py --date 20251013 --report
```

**출력**:
- 전체 파일 품질 점수
- 문제 파일 목록
- 검증 리포트 (txt)

---

## 검증 프로세스

### 매일 장 마감 후 (15:40)

#### Step 1: 데이터 확인
```bash
# 오늘 저장된 파일 확인
ls cache/minute_data/*_$(date +%Y%m%d).pkl

# Windows PowerShell
Get-ChildItem cache\minute_data\*_20251013.pkl
```

**기대 결과**:
- 오늘 선정된 종목 수만큼 파일 존재
- 파일 크기 적정 (각 100KB~500KB)

#### Step 2: 데이터 품질 검증
```bash
python auto_verify_consistency.py --report
```

**기대 결과**:
```
✅ 검증 대상: 40개 파일
✅ 정상: 40개 (100.0%)
⚠️ 이상: 0개 (0.0%)
```

**문제 발생 시**:
```
⚠️ 이상: 3개 (7.5%)
발견된 문제점:
   - 003160: 데이터 부족 (350/390)
   - 030530: 중복 데이터: 5개
   - 042700: 09:00 시작 아님 (09:05)
```

#### Step 3: 신호 일치성 검증 (샘플)
```bash
# 거래가 있었던 종목 중 하나로 테스트
python verify_realtime_simulation_consistency.py --stock 003160 --date 20251013
```

**기대 결과**:
```
✅ 3분봉 변환: 일치
✅ 신호 생성: 5/5 일치
```

#### Step 4: 시뮬레이션 실행
```bash
python utils\signal_replay.py --date 20251013 --export txt
```

**비교 항목**:
- 신호 발생 시점 (시간)
- 매수 가격 (4/5가)
- 매도 신호 (손익비)

#### Step 5: 상세 비교 (이상 발견 시)
```bash
python detailed_logic_comparison.py --stock 003160 --date 20251013
```

---

## 문제 해결

### 문제 1: 파일이 저장 안 됨

**증상**:
```
ls cache/minute_data/*_20251013.pkl
→ 파일 없음
```

**원인**:
- 15:30 업데이트가 실행 안 됨
- 프로그램이 15:30 전에 종료됨

**해결**:
```python
# core/intraday_stock_manager.py
# batch_update_realtime_data() 함수 확인
if current_time.hour == 15 and current_time.minute >= 30:
    if not hasattr(self, '_data_saved_today'):
        self._save_minute_data_to_cache()  # 호출 확인
```

### 문제 2: 데이터 부족

**증상**:
```
⚠️ 003160: 데이터 부족 (350/390)
```

**원인**:
- HTS 분봉 누락
- API 지연

**해결**:
```bash
# 해당 종목 재수집
python -c "
from save_candidate_data import CandidateDataSaver
import asyncio

async def main():
    saver = CandidateDataSaver()
    await saver.save_minute_data('003160', '20251013')

asyncio.run(main())
"
```

### 문제 3: 중복 데이터

**증상**:
```
⚠️ 030530: 중복 데이터: 5개
```

**원인**:
- historical + realtime 병합 시 중복 제거 누락
- API가 동일 분봉을 2번 반환

**해결**:
```python
# 이미 해결됨 (get_combined_chart_data에서 중복 제거)
combined_data = combined_data.drop_duplicates(subset=['datetime'], keep='last')
```

### 문제 4: 시간 불연속

**증상**:
```
⚠️ 042700: 시간 불연속: 10:39 → 10:42
```

**원인**:
- HTS에서 특정 분봉 누락
- API 서버 데이터 불완전

**해결**:
```python
# 이미 해결됨 (2개 분봉 수집)
# 매번 현재 + 1분 전 수집하여 누락 복구
```

### 문제 5: 09:00 시작 아님

**증상**:
```
⚠️ 089890: 09:00 시작 아님 (09:05)
```

**원인**:
- 종목 선정이 09:05에 되어서 그 이전 데이터 없음

**해결**:
- 정상 (선정 시점부터 데이터 수집이 정상)
- 단, signal_replay는 09:00부터 필요하므로 별도 수집 필요

---

## 🎯 성공 기준

### 데이터 품질
- ✅ 전체 파일의 95% 이상 정상
- ✅ 각 파일 최소 300개 분봉 (09:00~15:00 기준)
- ✅ 중복 없음
- ✅ 시간 연속성 유지

### 신호 일치성
- ✅ 3분봉 변환: 100% 일치
- ✅ 신호 생성: 100% 일치
- ✅ 매수 가격: 100% 일치

### 수익률 차이
- ✅ 개별 거래: 0.1~1.0% 차이 허용
- ✅ 전체 평균: 0.5% 이내 차이

---

## 📊 일일 체크리스트

### 장 마감 후 (15:40~16:00)

- [ ] 1. 실시간 데이터 저장 확인
  ```bash
  ls cache/minute_data/*_20251013.pkl | wc -l
  # 기대: 선정 종목 수와 일치
  ```

- [ ] 2. 자동 품질 검증
  ```bash
  python auto_verify_consistency.py --report
  # 기대: 95% 이상 정상
  ```

- [ ] 3. 샘플 종목 상세 검증
  ```bash
  python detailed_logic_comparison.py --stock 003160
  # 기대: 모든 단계 일치
  ```

- [ ] 4. 시뮬레이션 실행
  ```bash
  python utils\signal_replay.py --date 20251013 --export txt
  # 기대: 신호 시점/가격 일치
  ```

- [ ] 5. 결과 비교 및 기록
  - 신호 일치율: __%
  - 수익률 차이: __% (허용: 0.5% 이내)
  - 데이터 품질: __%

---

## 🚨 즉시 조치 필요한 경우

### 데이터 품질 < 90%
```bash
# 문제 파일 재수집
python save_candidate_data.py --date 20251013 --minute-only

# 재검증
python auto_verify_consistency.py --date 20251013
```

### 신호 불일치 발견
```bash
# 상세 분석
python detailed_logic_comparison.py --stock {문제종목}

# 코드 확인:
# 1. PullbackCandlePattern.generate_improved_signals() 호출 파라미터
# 2. TimeFrameConverter.convert_to_3min_data() 입력 데이터
# 3. 중복 제거 로직
```

### 수익률 차이 > 2%
```bash
# 매도 가격 차이 확인
# 1. real_trading_records 테이블에서 실제 체결가 조회
# 2. signal_replay 결과와 비교
# 3. 1분봉 고가/저가 vs 실제 체결가 분석
```

---

## 📁 파일 구조

```
RoboTrader/
├── cache/minute_data/          # 분봉 캐시
│   ├── 003160_20251013.pkl    # 실시간 수집 데이터
│   ├── 030530_20251013.pkl
│   └── ...
│
├── 검증 도구/
│   ├── compare_realtime_vs_simulation_data.py     # 데이터 비교
│   ├── verify_realtime_simulation_consistency.py  # 신호 일치성 검증
│   ├── detailed_logic_comparison.py               # 로직 상세 비교
│   └── auto_verify_consistency.py                 # 자동 품질 검증
│
├── 분석 문서/
│   ├── REALTIME_SIMULATION_DIFFERENCES.md  # 차이점 분석
│   ├── ANALYSIS_SUMMARY.md                 # 최종 요약
│   └── VERIFICATION_GUIDE.md               # 검증 가이드 (본 문서)
│
└── 핵심 로직/
    ├── core/intraday_stock_manager.py          # 실시간 데이터 수집
    ├── core/trading_decision_engine.py         # 실시간 매매 판단
    ├── core/timeframe_converter.py             # 3분봉 변환
    └── utils/signal_replay.py                  # 시뮬레이션
```

---

## 🔧 현재 적용된 개선 사항

### ✅ 데이터 수집 개선
1. **2개 분봉 수집**: 현재 + 1분 전 (누락 방지)
2. **15:30 자동 저장**: pickle 파일로 저장
3. **품질 검사 강화**: 정렬 + 중복 제거
4. **DB 복원**: 프로그램 재시작 시 오늘 종목 복원

### ✅ 로직 통일
1. **손익비**: trading_config.json 통일
2. **신호 함수**: 동일 함수 사용 확인
3. **3분봉 변환**: 동일 함수 사용 확인

### ✅ 검증 자동화
1. **자동 품질 검증**: auto_verify_consistency.py
2. **데이터 비교**: compare_realtime_vs_simulation_data.py
3. **신호 검증**: verify_realtime_simulation_consistency.py
4. **상세 분석**: detailed_logic_comparison.py

---

## 📊 기대 검증 결과

### 정상 케이스 (95% 이상)

```
날짜: 2025-10-13
전체 파일: 40개
✅ 정상: 38개 (95.0%)
⚠️ 이상: 2개 (5.0%)

발견된 문제점:
   - 003160: 데이터 부족 (380/390) - 선정 시점 늦음 (정상)
   - 089890: 09:00 시작 아님 (09:05) - 선정 시점 늦음 (정상)

신호 일치성 (샘플 10종목):
✅ 3분봉 변환: 10/10 일치
✅ 신호 생성: 10/10 일치
✅ 매수 가격: 10/10 일치

최종 평가: ✅ 우수
```

### 문제 케이스 (< 90%)

```
날짜: 2025-10-13
전체 파일: 40개
✅ 정상: 32개 (80.0%)
⚠️ 이상: 8개 (20.0%)

발견된 문제점:
   - 003160: 중복 데이터: 10개
   - 030530: 시간 불연속: 10:39 → 10:42
   - 042700: 데이터 부족 (250/390)
   ...

최종 평가: ❌ 재수집 필요
→ python save_candidate_data.py --date 20251013 --minute-only
```

---

## ✅ 최종 결론

### 데이터가 동일하면:
- **신호**: 100% 일치 보장
- **매수 가격**: 100% 일치 보장
- **매도 신호**: 100% 일치 보장
- **최종 수익률**: 0.1~1.0% 차이 (매도가 차이)

### 데이터 품질 유지 방법:
1. ✅ 매분 2개 분봉 수집 (누락 복구)
2. ✅ 품질 검사 강화 (정렬 + 중복 제거)
3. ✅ 15:30 자동 저장
4. ✅ 매일 자동 검증

### 검증 주기:
- **매일**: auto_verify_consistency.py
- **주간**: 전체 종목 상세 검증
- **월간**: 누적 일치율 통계

---

## 📞 문의 및 개선

### 검증 실패 시
1. 로그 확인: `logs/` 디렉토리
2. 문제 파일 재수집
3. 상세 분석 스크립트 실행
4. 필요시 코드 수정

### 개선 아이디어
- [ ] 매도가 차이 최소화 (실시간에서도 1분봉 사용)
- [ ] 실시간 체결 정보 DB 저장
- [ ] 일치율 통계 자동 수집
- [ ] 텔레그램 알림 연동

