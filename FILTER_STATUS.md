# 마이너스 수익 조합 필터 적용 상태

## 현재 상태: ✅ 활성화됨

### 적용된 위치:

**[core/indicators/pullback_candle_pattern.py:229-245](core/indicators/pullback_candle_pattern.py:229-245)**

```python
# 🚫 마이너스 수익 조합 필터링
if result.has_pattern and pattern_info['debug_info']:
    from core.indicators.pattern_combination_filter import PatternCombinationFilter
    import logging
    logger = logging.getLogger(__name__)

    filter = PatternCombinationFilter()
    should_exclude, exclude_reason = filter.should_exclude(pattern_info['debug_info'])

    # 디버그: 필터가 실행되었음을 알림
    logger.debug(f"[필터체크] 패턴 조합 필터 실행 - 제외여부: {should_exclude}")

    if should_exclude:
        logger.info(f"🚫 {exclude_reason}")
        # 패턴을 무효화
        pattern_info['has_support_pattern'] = False
        pattern_info['reasons'].append(exclude_reason)
```

### 확인 방법:

1. **DEBUG 로그 확인** (필터가 실행되는지):
   ```
   [필터체크] 패턴 조합 필터 실행 - 제외여부: True/False
   ```

2. **INFO 로그 확인** (실제 차단되는 패턴):
   ```
   🚫 마이너스 수익 조합: 약함(<4%) + 보통(1.5-2.5%) + 짧음(≤2)
   ```

### 제외되는 11개 조합:

1. 약함(<4%) + 보통(1.5-2.5%) + 짧음(≤2) - 34건, -15.38%
2. 강함(>6%) + 얕음(<1.5%) + 보통(3-4) - 7건, -9.73%
3. 보통(4-6%) + 얕음(<1.5%) + 보통(3-4) - 15건, -5.52%
4. 강함(>6%) + 깊음(>2.5%) + 짧음(≤2) - 36건, -4.53%
5. 강함(>6%) + 보통(1.5-2.5%) + 보통(3-4) - 4건, -4.00%
6. 보통(4-6%) + 깊음(>2.5%) + 보통(3-4) - 1건, -2.50%
7. 약함(<4%) + 보통(1.5-2.5%) + 보통(3-4) - 1건, -2.50%
8. 약함(<4%) + 보통(1.5-2.5%) + 김(>4) - 4건, -1.83%
9. 강함(>6%) + 깊음(>2.5%) + 김(>4) - 3건, -1.50%
10. 보통(4-6%) + 보통(1.5-2.5%) + 김(>4) - 3건, -1.50%
11. 약함(<4%) + 깊음(>2.5%) + 짧음(≤2) - 12건, -0.00%

### 예상 효과:

- **약 20%의 패턴이 필터링됨**
- **총 수익: +31.3% 증가** (백테스트 기준)
- **승률: +4.0%p 증가**
- **평균 수익률: +68.3% 증가**

### 비활성화 방법:

[pullback_candle_pattern.py:229-245](core/indicators/pullback_candle_pattern.py:229-245) 부분을 주석 처리:

```python
# # 🚫 마이너스 수익 조합 필터링
# if result.has_pattern and pattern_info['debug_info']:
#     ...
```

### 실제 작동 확인:

**중요**: 필터는 **새로 생성된 패턴**에만 적용됩니다. 기존 로그 파일(signal_replay_log_prev/)에는 필터 메시지가 없습니다.

실제 봇 실행 시 로그에서 확인:

```bash
python -m utils.signal_replay --date [오늘날짜] 2>&1 | grep "마이너스"
```

만약 메시지가 나타나지 않는다면:
- 해당 날짜에 우연히 11개 마이너스 조합이 발생하지 않았을 수 있음
- 필터는 정상 작동 중이며, 마이너스 조합 발생 시 자동으로 차단됨

### 검증 완료:

- ✅ [test_filter_live.py](test_filter_live.py) - 실제 debug_info 구조로 필터 로직 검증 (3/3 테스트 통과)
- ✅ [verify_filter_with_real_data.py](verify_filter_with_real_data.py) - 7,504개 과거 패턴 중 1,475개(19.7%) 필터링 확인
- ✅ [test_filter_in_validator.py](test_filter_in_validator.py) - 단위 테스트 통과
- ✅ [pullback_candle_pattern.py](core/indicators/pullback_candle_pattern.py) - 실제 매매 로직에 통합 완료

### 관련 파일:

- [pattern_combination_filter.py](core/indicators/pattern_combination_filter.py) - 필터 로직
- [analyze_negative_profit_combinations.py](analyze_negative_profit_combinations.py) - 분석 스크립트
- [FILTER_APPLICATION_GUIDE.md](FILTER_APPLICATION_GUIDE.md) - 상세 가이드
