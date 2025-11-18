# 매일 필터 업데이트 빠른 시작 가이드

## 📌 요약

**매일 자동으로 패턴 조합을 분석하고 필터를 업데이트하는 시스템**

---

## 🚀 빠른 실행

### 방법 1: 배치 스크립트 (추천)

```bash
# 더블 클릭 또는 명령줄에서 실행
update_filter_daily.bat
```

### 방법 2: Python 명령어

```bash
# 전체 데이터 분석 및 자동 업데이트
python daily_filter_updater.py --all --update

# 최근 1주일만 분석
python daily_filter_updater.py --start 20251110 --end 20251117

# 분석만 (업데이트 안 함)
python daily_filter_updater.py --all
```

---

## 📊 실행 결과

### 1. 콘솔 출력
- 날짜별 데이터 로딩 현황
- 조합별 통계 (제외 조합, 상위 조합)
- 업데이트 완료 메시지

### 2. 일일 보고서 생성 ⭐
**자동 생성**: `filter_reports/filter_analysis_YYYYMMDD.md`

**포함 내용**:
- ✅ 전체 통계 (조합 수, 거래 수, 승률)
- 🚫 제외된 조합 상세 (12개)
- 🏆 상위 수익 조합 Top 5
- 💡 지지길이별/상승강도별 인사이트
- 📝 다음 단계 가이드

### 3. 필터 업데이트 (--update 시)
- **백업**: `core/indicators/pattern_combination_filter_backup_YYYYMMDD_HHMMSS.py`
- **업데이트**: `core/indicators/pattern_combination_filter.py`

---

## 📅 일일 워크플로우

```
1. 시뮬레이션 실행 (09:00~15:30)
   └─> pattern_data_log 자동 생성

2. 하루 끝에 필터 업데이트 (20:00)
   └─> update_filter_daily.bat 실행
   └─> 또는 작업 스케줄러 등록

3. 보고서 확인
   └─> filter_reports/filter_analysis_YYYYMMDD.md

4. 다음날 시뮬레이션 재시작
   └─> 새로운 필터 자동 적용
```

---

## 📈 현재 필터 상태

**마지막 업데이트**: 2025-11-17 19:34:28

**분석 데이터**:
- 총 조합: 26개
- 총 거래: 7,218건
- 제외 조합: 12개

**최악의 조합**:
1. 강함(>6%) + 얕음(<1.5%) + 짧음(≤2) → -219.14%

**최고의 조합**:
1. 약함(<4%) + 얕음(<1.5%) + 짧음(≤2) → +682.78%

---

## 🔧 작업 스케줄러 등록 (자동화)

### Windows 작업 스케줄러 설정

1. `작업 스케줄러` 실행 (taskschd.msc)
2. `작업 만들기` 클릭
3. 설정:
   - **이름**: "RoboTrader 필터 업데이트"
   - **트리거**: 매일 오후 8시
   - **동작**: 프로그램 시작
     - 프로그램: `D:\GIT\RoboTrader\update_filter_daily.bat`
     - 시작 위치: `D:\GIT\RoboTrader`
4. 저장

---

## 📂 생성되는 파일들

```
D:\GIT\RoboTrader\
├── filter_reports/                          ⭐ 일일 보고서 (자동 생성)
│   ├── filter_analysis_20251117.md         매일 생성
│   ├── filter_analysis_20251118.md
│   └── ...
│
├── core/indicators/
│   ├── pattern_combination_filter.py       필터 (자동 업데이트)
│   └── pattern_combination_filter_backup_*.py  백업
│
└── pattern_data_log/                        입력 데이터
    ├── pattern_data_20251117.jsonl
    └── ...
```

---

## 💡 팁

### 주간 분석
```bash
# 매주 일요일에 지난 주 데이터만 분석
python daily_filter_updater.py --start 20251110 --end 20251117
```

### 월별 비교
```bash
# 각 월별로 분석하여 트렌드 파악
python daily_filter_updater.py --start 20250901 --end 20250930 > sep.txt
python daily_filter_updater.py --start 20251001 --end 20251031 > oct.txt
python daily_filter_updater.py --start 20251101 --end 20251130 > nov.txt
```

### 엄격한 필터링
```bash
# 최소 10건 이상, 총 손실 -5% 이상만 제외
python daily_filter_updater.py --all --min-trades 10 --min-loss -5.0 --update
```

---

## ⚠️ 주의사항

1. **시뮬레이션 재시작 필수**
   - 필터 업데이트 후 반드시 시뮬레이션 재시작
   - 재시작 전까지 기존 필터 사용

2. **데이터 누적 필요**
   - 최소 100건 이상의 거래 데이터 권장
   - 현재: 7,218건 (충분함 ✅)

3. **백업 관리**
   - 백업 파일은 자동 생성됨
   - 오래된 백업은 정기적으로 정리

4. **보고서 확인**
   - 매번 보고서를 확인하여 필터 성능 모니터링
   - 이상한 패턴 발견 시 임계값 조정

---

## 🆘 문제 해결

### Q: "패턴 파일 없음" 오류
**A**: 시뮬레이션을 먼저 실행하여 pattern_data_log 생성

### Q: "분석된 조합이 없음"
**A**: `--min-trades 2`로 낮춰서 재시도

### Q: 보고서가 한글이 깨짐
**A**: 마크다운 뷰어에서 UTF-8 인코딩 설정

---

## 📚 더 자세한 정보

- **상세 가이드**: [FILTER_AUTO_UPDATE_GUIDE.md](FILTER_AUTO_UPDATE_GUIDE.md)
- **종합 보고서**: [FILTER_UPDATE_REPORT_20251117.md](FILTER_UPDATE_REPORT_20251117.md)
- **패턴 설명**: CLAUDE.md (눌림목 캔들 패턴)

---

## 📞 지원

문제 발생 시:
1. `filter_reports/` 보고서 확인
2. 로그 파일 확인
3. 백업 파일로 복원

---

**마지막 업데이트**: 2025-11-17
**버전**: 1.0

*간편하게 사용하려면 `update_filter_daily.bat`를 더블 클릭하세요!*
