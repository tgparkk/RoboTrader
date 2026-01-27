# 동적 손익비 - 빠른 시작 가이드

## 🎯 3분 요약

### 이것이 뭔가요?

**패턴별로 다른 손익비를 자동으로 적용**하는 시스템입니다.

- 기존: 모든 매매에 손절 -2.5%, 익절 +3.5% 고정
- 개선: 패턴 특성에 따라 손절 -1.5~-5.0%, 익절 +3.5~+7.5% 자동 조정

### 얼마나 좋아지나요?

**백테스트 결과 (9월~12월, 2,362건)**:
- 평균 수익률: 1.56% → **2.21% (+42% 향상)**
- 총 수익률: 3,683.83% → **5,209.36% (+1,525.53%p 향상)**

### 안전한가요?

**매우 안전합니다**:
- ✅ 플래그 하나로 ON/OFF (JSON 파일 수정만)
- ✅ 문제 발생 시 10초 이내 즉시 원복
- ✅ 기본값 `false` (비활성화 상태)
- ✅ 오류 시 자동으로 기존 로직 사용

---

## 🔧 ON/OFF 방법 (30초)

### 활성화

1. `config/trading_config.json` 파일 열기
2. 아래 부분 찾기:
   ```json
   "use_dynamic_profit_loss": false
   ```
3. `true`로 변경:
   ```json
   "use_dynamic_profit_loss": true
   ```
4. 저장
5. **10초 대기** → 자동 적용

### 비활성화 (원복)

1. 위 파일에서 `false`로 변경
2. 저장
3. 10초 대기 → 기존 로직 자동 적용

---

## 🧪 테스트 방법 (5분)

### 1. 플래그 작동 확인

```bash
python test_flag_switch.py
```

**결과 확인**:
- `[OK] 플래그 일치: 정상 작동` 메시지 확인
- 플래그 `false` → 고정 손익비 (-2.5% / +3.5%)
- 플래그 `true` → 동적 손익비 (패턴별 차이)

### 2. 백테스트 확인

```bash
python test_dynamic_profit_loss.py --start 20251201 --end 20251222
```

**결과 확인**:
- 고정 vs 동적 손익비 성과 비교
- 평균 수익률 42% 향상 확인

### 3. 시뮬레이션 비교

```bash
# 플래그 false 상태에서
python -m utils.signal_replay --date 20251222 --export txt

# config.json에서 true로 변경 → 10초 대기

# 플래그 true 상태에서
python -m utils.signal_replay --date 20251222 --export txt

# 두 결과 파일 비교
# signal_replay_log/signal_new2_replay_20251222_9_00_0.txt
```

**확인 사항**:
- 로그에 `🔧 [동적 손익비]` 메시지 출력
- 패턴별로 다른 손익비 적용

---

## 📊 어떤 패턴이 가장 좋나요?

### Top 3 패턴

1. **low + strong_decrease** (최고 성과)
   - 손익비: 손절 -5.0% / 익절 +7.5%
   - 평균 수익률: **+3.50%**
   - 승률: **78.6%**

2. **very_low + weak_decrease**
   - 손익비: 손절 -4.5% / 익절 +7.0%
   - 평균 수익률: **+2.73%**
   - 승률: **72.2%**

3. **very_low + normal_decrease**
   - 손익비: 손절 -5.0% / 익절 +7.0%
   - 평균 수익률: **+2.65%**
   - 승률: **72.5%**

### 패턴 의미

**지지 거래량** (상승 구간 최대 거래량 대비):
- `very_low`: 15% 미만
- `low`: 15~25%
- `normal`: 25% 이상

**하락 거래량 감소** (상승 구간 평균 거래량 대비):
- `strong_decrease`: 30% 미만 (강한 감소)
- `normal_decrease`: 30~60%
- `weak_decrease`: 60% 이상 (약한 감소)

---

## ⚠️ 실거래 적용 전 필수 체크

### ✅ 완료 확인

- [x] 백테스트 결과 확인 (42% 향상)
- [x] 코드 통합 완료
- [x] 플래그 시스템 작동 확인

### 🔲 실행 필요

- [ ] 플래그 true/false 전환 테스트
- [ ] 시뮬레이션 비교 테스트
- [ ] 로그에서 동적 손익비 적용 확인
- [ ] 최소 1주일 시뮬레이션 테스트
- [ ] 소액 실거래 1주일 테스트

### ⚠️ 주의사항

1. **현재 기본값**: `false` (비활성화)
2. **반드시 시뮬 테스트 먼저**: 실거래 전 충분히 테스트
3. **소액으로 시작**: 전체 자금의 10% 정도로 1주일 테스트
4. **문제 발생 시**: 즉시 `false`로 롤백

---

## 📞 자주 묻는 질문

### Q. 지금 바로 실거래에 적용해도 되나요?

**A**: 아니요. 반드시 아래 순서로 진행하세요:
1. 시뮬레이션 충분히 테스트 (1주일 이상)
2. 소액 실거래 테스트 (1주일)
3. 문제 없으면 점진적 확대

### Q. 플래그를 true로 했는데 변화가 없어요.

**A**:
1. JSON 파일 저장 확인
2. 10초 대기 (캐싱 갱신)
3. `python test_flag_switch.py` 실행
4. 로그에서 `🔧 [동적 손익비]` 확인

### Q. 기존 로직으로 돌아가고 싶어요.

**A**:
```json
{"use_dynamic_profit_loss": false}
```
저장 → 10초 대기 → 자동 원복

### Q. 어떤 파일을 수정했나요?

**A**: 총 5개 파일 수정 완료
1. `config/trading_config.json` - 플래그
2. `config/dynamic_profit_loss_config.py` - 계산 모듈
3. `core/models.py` - 패턴 정보 저장
4. `core/trading_decision_engine.py` - 손익비 적용
5. `core/indicators/pullback/support_pattern_analyzer.py` - 패턴 분류

**모든 수정은 원복 가능**하며, 플래그만 변경하면 즉시 전환됩니다.

---

## 📚 더 자세한 내용은?

1. **[동적_손익비_완료_요약.md](동적_손익비_완료_요약.md)** - 전체 요약 (권장)
2. [DYNAMIC_PROFIT_LOSS_INTEGRATION_COMPLETE.md](DYNAMIC_PROFIT_LOSS_INTEGRATION_COMPLETE.md) - 통합 완료 보고서
3. [DYNAMIC_PROFIT_LOSS_USAGE_GUIDE.md](DYNAMIC_PROFIT_LOSS_USAGE_GUIDE.md) - 상세 사용 가이드
4. [PATTERN_PROFIT_LOSS_ANALYSIS_REPORT.md](PATTERN_PROFIT_LOSS_ANALYSIS_REPORT.md) - 패턴 분석 결과
5. [DYNAMIC_PROFIT_LOSS_BACKTEST_RESULT.md](DYNAMIC_PROFIT_LOSS_BACKTEST_RESULT.md) - 백테스트 결과

---

## ✅ 다음 단계

1. **지금 바로**: `python test_flag_switch.py` 실행
2. **오늘 안에**: 시뮬레이션 테스트 (플래그 true/false 비교)
3. **1주일 후**: 시뮬 결과 확인 → 소액 실거래 시작
4. **2주일 후**: 소액 테스트 성공 시 점진적 확대

---

**작성일**: 2025-12-22
**소요 시간**: 플래그 변경 30초, 테스트 5분
**현재 상태**: 실거래 코드 통합 완료, 시뮬 테스트 권장
