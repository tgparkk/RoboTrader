# 동적 손익비 시스템 - 실거래 코드 통합 완료

## ✅ 최종 완료 사항

**C++ `#ifndef` 스타일 플래그 기반 동적 손익비 시스템이 실거래 코드에 완전히 통합되었습니다.**

### 구현 완료 파일 (총 5개)

1. **config/trading_config.json** - 마스터 ON/OFF 스위치
2. **config/dynamic_profit_loss_config.py** - 동적 손익비 계산 모듈
3. **core/models.py** - TradingStock에 pattern_info 필드 추가
4. **core/trading_decision_engine.py** - 실거래 손익비 적용 로직 수정
5. **core/indicators/pullback/support_pattern_analyzer.py** - 패턴 분류 로직 추가

---

## 🔧 작동 방식

### 1단계: 패턴 분석 (support_pattern_analyzer.py)

매수 신호 발생 시 4단계 패턴 분석 후 패턴 특성 분류:

```python
# 지지 거래량 분류
support_volume_ratio = support.avg_volume / uptrend.max_volume
if support_volume_ratio < 0.15:
    support_volume_class = 'very_low'      # 매우 낮음 (<15%)
elif support_volume_ratio < 0.25:
    support_volume_class = 'low'           # 낮음 (15-25%)
else:
    support_volume_class = 'normal'        # 보통 (25%+)

# 하락 거래량 분류
decline_volume_ratio = decline.avg_volume / uptrend.volume_avg
if decline_volume_ratio < 0.3:
    decline_volume_class = 'strong_decrease'    # 강한 감소 (<30%)
elif decline_volume_ratio < 0.6:
    decline_volume_class = 'normal_decrease'    # 보통 감소 (30-60%)
else:
    decline_volume_class = 'weak_decrease'      # 약한 감소 (60%+)
```

**결과**: `debug_info`에 4가지 정보 추가
- `support_volume_class`
- `decline_volume_class`
- `support_volume_ratio`
- `decline_volume_ratio`

### 2단계: 패턴 정보 저장 (trading_decision_engine.py, Line 1075-1084)

매수 신호 확정 시 패턴 정보를 `trading_stock.pattern_info`에 저장:

```python
# 🔧 동적 손익비를 위한 패턴 정보 저장
debug_info = signal_strength.pattern_data.get('debug_info', {})
if debug_info:
    trading_stock.pattern_info = {
        'support_volume': debug_info.get('support_volume_class'),
        'decline_volume': debug_info.get('decline_volume_class'),
        'support_volume_ratio': debug_info.get('support_volume_ratio'),
        'decline_volume_ratio': debug_info.get('decline_volume_ratio')
    }
```

### 3단계: 손익비 적용 (trading_decision_engine.py, Line 759-792)

매 체크마다 플래그 확인 후 동적 손익비 적용:

```python
# ⚙️ 동적 손익비 체크 (C++ ifndef 스타일)
if hasattr(config.risk_management, 'use_dynamic_profit_loss') and config.risk_management.use_dynamic_profit_loss:
    # ✅ 동적 손익비 활성화
    from config.dynamic_profit_loss_config import DynamicProfitLossConfig

    pattern_info = getattr(trading_stock, 'pattern_info', None)
    if pattern_info:
        support_volume = pattern_info.get('support_volume', None)
        decline_volume = pattern_info.get('decline_volume', None)

        if support_volume and decline_volume:
            # 패턴 조합 기반 최적 손익비 조회
            ratio = DynamicProfitLossConfig.get_ratio_by_pattern(support_volume, decline_volume)
            take_profit_percent = ratio['take_profit']
            stop_loss_percent = abs(ratio['stop_loss'])

            self.logger.info(f"🔧 [동적 손익비] 패턴: {support_volume}+{decline_volume}, "
                           f"손절 {stop_loss_percent:.1f}% / 익절 {take_profit_percent:.1f}%")
else:
    # ⚙️ 기존 고정 손익비 사용
    take_profit_percent = config.risk_management.take_profit_ratio * 100
    stop_loss_percent = config.risk_management.stop_loss_ratio * 100
```

---

## 🎯 ON/OFF 방법

### ✅ 활성화 (동적 손익비 사용)

`config/trading_config.json` 파일 수정:

```json
{
  "risk_management": {
    "use_dynamic_profit_loss": true
  }
}
```

**저장 후 최대 10초 이내 자동 반영** (캐싱 갱신)

### ⚙️ 비활성화 (기존 로직 사용)

```json
{
  "risk_management": {
    "use_dynamic_profit_loss": false
  }
}
```

**현재 기본값**: `false` (안전을 위해 비활성화 상태)

---

## 📊 패턴별 손익비 테이블

동적 손익비 활성화 시 사용되는 9개 조합:

| 지지 거래량 | 하락 거래량 | 손절 | 익절 | 평균 수익률 | 승률 |
|-----------|-----------|-----|-----|-----------|------|
| low | strong_decrease | -5.0% | +7.5% | **+3.50%** | 78.6% |
| very_low | weak_decrease | -4.5% | +7.0% | **+2.73%** | 72.2% |
| very_low | normal_decrease | -5.0% | +7.0% | **+2.65%** | 72.5% |
| low | weak_decrease | -5.0% | +7.5% | **+2.45%** | 75.0% |
| low | normal_decrease | -1.5% | +7.5% | **+2.36%** | 60.0% |
| normal | strong_decrease | -5.0% | +7.5% | **+2.09%** | 77.8% |
| very_low | strong_decrease | -5.0% | +7.5% | **+2.02%** | 72.7% |
| normal | normal_decrease | -5.0% | +5.0% | **+1.27%** | 60.0% |
| normal | weak_decrease | -5.0% | +7.5% | **+0.54%** | 50.0% |

**조합이 없는 경우**: 기본값 사용 (손절 -2.5%, 익절 +3.5%)

---

## 📁 수정된 파일 상세

### 1. config/trading_config.json

```json
{
  "risk_management": {
    "max_position_count": 20,
    "max_position_ratio": 0.3,
    "stop_loss_ratio": 0.025,
    "take_profit_ratio": 0.035,
    "max_daily_loss": 0.1,
    "use_dynamic_profit_loss": false    // ⚙️ 마스터 스위치
  }
}
```

### 2. config/dynamic_profit_loss_config.py

**핵심 메서드**:
- `is_dynamic_enabled()`: 플래그 확인 (10초 캐싱)
- `get_ratio_by_pattern(support_volume_class, decline_volume_class)`: 패턴 조합 기반 손익비 조회

**안전 장치**:
- 플래그 `false` 시 자동으로 기본값 반환
- 오류 발생 시 기본값 반환
- 조합이 없을 경우 기본값 반환

### 3. core/models.py (Line 177-178)

```python
@dataclass
class TradingStock:
    # ... 기존 필드들 ...

    # 🔧 동적 손익비를 위한 패턴 정보 (support_volume_class, decline_volume_class 포함)
    pattern_info: Optional[Dict[str, Any]] = None
```

**저장 내용**:
```python
{
    'support_volume': 'low',           # very_low, low, normal
    'decline_volume': 'strong_decrease',  # strong_decrease, normal_decrease, weak_decrease
    'support_volume_ratio': 0.18,      # 실제 비율 (분석용)
    'decline_volume_ratio': 0.25       # 실제 비율 (분석용)
}
```

### 4. core/trading_decision_engine.py

**A. 패턴 정보 저장 (Line 1075-1084)**

매수 신호 발생 시 `pattern_info` 추출 및 저장

**B. 손익비 적용 (Line 759-792)**

`_check_simple_stop_profit_conditions` 메서드 수정:
- 플래그 체크
- `true`: 패턴 정보 기반 동적 손익비 적용
- `false`: 기존 고정 손익비 사용

### 5. core/indicators/pullback/support_pattern_analyzer.py (Line 298-358)

`_analyze_all_scenarios` 메서드 내 `debug_info` 생성 부분:

**추가된 계산**:
- `support_volume_ratio` 계산
- `support_volume_class` 분류 (very_low/low/normal)
- `decline_volume_ratio` 계산
- `decline_volume_class` 분류 (strong_decrease/normal_decrease/weak_decrease)

**결과**: `debug_info`에 4개 필드 추가

---

## 🚀 실거래 적용 가이드

### Phase 1: 시뮬레이션 테스트 (필수)

```bash
# 1. 플래그 작동 확인
python test_flag_switch.py

# 2. 백테스트 실행
python test_dynamic_profit_loss.py --start 20251201 --end 20251222

# 3. 시뮬레이션 실행 (플래그 false)
python -m utils.signal_replay --date 20251222 --export txt

# 4. 시뮬레이션 실행 (플래그 true)
# config.json 수정: "use_dynamic_profit_loss": true
python -m utils.signal_replay --date 20251222 --export txt

# 5. 결과 비교
# - 손익비가 패턴별로 다르게 적용되는지 확인
# - 로그에서 "🔧 [동적 손익비]" 메시지 확인
```

### Phase 2: 소액 실거래 테스트

1. **준비**:
   - 전체 자금의 10% 정도로 테스트
   - 1주일 동안 모니터링

2. **활성화**:
   ```json
   {"use_dynamic_profit_loss": true}
   ```

3. **모니터링**:
   - 로그에서 손익비 적용 확인
   - 패턴별 성과 기록
   - 예상치 못한 동작 확인

4. **문제 발생 시 즉시 롤백**:
   ```json
   {"use_dynamic_profit_loss": false}
   ```

### Phase 3: 전면 적용

1. 소액 테스트에서 문제 없음 확인 후
2. 전체 자금으로 확대
3. 지속적 모니터링
4. 월 1회 백테스트로 손익비 재조정

---

## ⚠️ 주의사항

### 1. 코드 수정 완료 상태

- ✅ 모든 필수 파일 수정 완료
- ✅ 플래그 시스템 구현 완료
- ✅ 안전 장치 내장 (기본값 자동 반환)
- ⚠️ 실거래 테스트는 아직 미실시

### 2. 플래그 변경 후 반영 시간

- 설정 파일 변경 후 **최대 10초** 소요
- 10초 캐싱으로 성능 최적화
- 변경 즉시 반영 안 됨 (정상)

### 3. 원복 방법

**즉시 원복 (코드 수정 불필요)**:

```json
{"use_dynamic_profit_loss": false}
```

저장 후 10초 대기 → 기존 로직 자동 적용

### 4. 로그 확인

동적 손익비 적용 시 로그 예시:

```
[INFO] 🔧 [동적 손익비] 패턴: low+strong_decrease, 손절 5.0% / 익절 7.5%
[DEBUG] 🔧 패턴 정보 저장: {'support_volume': 'low', 'decline_volume': 'strong_decrease', ...}
```

고정 손익비 사용 시 이 메시지 없음

---

## 🎯 핵심 장점

### 1. C++ `#ifndef` 스타일

```python
if not cls.is_dynamic_enabled():
    return {'stop_loss': -2.5, 'take_profit': 3.5}  # 기존 로직

# 활성화 시에만 아래 코드 실행
# ... 동적 계산 로직 ...
```

**장점**: 플래그 하나로 전체 로직 전환

### 2. 안전장치 3중 체크

1. **플래그 미설정**: 자동으로 `false` (기본값)
2. **패턴 정보 없음**: 자동으로 기본값 반환
3. **오류 발생**: 자동으로 기본값 반환

### 3. 즉시 롤백

- JSON 파일 수정만으로 원복
- 코드 재배포 불필요
- 10초 이내 자동 반영

### 4. 백테스트 검증 완료

- 2,362건 분석 (9월~12월)
- 평균 수익률 **+42% 향상** (1.56% → 2.21%)
- 총 수익률 **+1,525.53%p 향상**

---

## 📋 최종 체크리스트

### 실거래 적용 전

- [x] 백테스트 완료 (42% 수익률 향상 확인)
- [x] 플래그 시스템 구현 완료
- [x] 실거래 코드 통합 완료
- [x] 안전장치 구현 완료
- [ ] 시뮬레이션으로 최소 1주일 테스트
- [ ] 플래그 true/false 전환 테스트
- [ ] 로그에서 손익비 적용 확인

### 실거래 적용 후

- [ ] 로그에서 "🔧 [동적 손익비]" 메시지 확인
- [ ] 패턴별 손익비 다르게 적용되는지 확인
- [ ] 소액 테스트 1주일 (문제 없음 확인)
- [ ] 전체 자금 적용
- [ ] 일일 성과 모니터링
- [ ] 월 1회 백테스트로 재조정

---

## 📞 문제 해결

### Q1. 플래그를 true로 했는데 여전히 고정 손익비가 적용됩니다.

**A**:
1. `config/trading_config.json` 파일 저장 확인
2. 10초 대기 (캐싱 갱신)
3. `python test_flag_switch.py` 실행하여 플래그 상태 확인
4. 로그에서 `🔧 [동적 손익비]` 메시지 확인
5. `pattern_info`가 제대로 저장되는지 확인 (로그 확인)

### Q2. 일부 종목에서만 동적 손익비가 적용되지 않습니다.

**A**:
- **원인**: `pattern_info`가 없거나 패턴 분류 실패
- **확인**: 로그에서 `🔧 패턴 정보 저장` 메시지 확인
- **정상**: 패턴 정보 없으면 자동으로 기본값 사용 (안전장치)

### Q3. 동적 손익비 적용 후 수익률이 하락했습니다.

**A**:
1. **즉시 롤백**: `"use_dynamic_profit_loss": false`
2. 패턴별 성과 분석 (어떤 조합이 문제인지)
3. 특정 패턴만 제외하고 재테스트
4. 손익비 조정 후 백테스트

### Q4. 특정 패턴만 동적 손익비를 적용하고 싶습니다.

**A**:
`config/dynamic_profit_loss_config.py`의 `get_ratio_by_pattern` 메서드 수정:

```python
@classmethod
def get_ratio_by_pattern(cls, support_volume_class, decline_volume_class):
    if not cls.is_dynamic_enabled():
        return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}

    # 특정 조합만 동적 손익비 사용
    if support_volume_class == 'low' and decline_volume_class == 'strong_decrease':
        return {'stop_loss': -5.0, 'take_profit': 7.5}  # 최고 성과 패턴만

    # 나머지는 기본값
    return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}
```

---

## 🎓 참고 문서

1. **README_DYNAMIC_PROFIT_LOSS.md** - 전체 개요 및 요약
2. **DYNAMIC_PROFIT_LOSS_USAGE_GUIDE.md** - 상세 사용 가이드
3. **PATTERN_PROFIT_LOSS_ANALYSIS_REPORT.md** - 패턴 분석 결과
4. **DYNAMIC_PROFIT_LOSS_BACKTEST_RESULT.md** - 백테스트 결과

---

**작성일**: 2025-12-22
**상태**: 실거래 코드 통합 완료, 시뮬레이션 테스트 후 적용 권장
**기본 플래그 상태**: `false` (비활성화, 안전)
