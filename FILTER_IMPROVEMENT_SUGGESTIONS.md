# 필터 개선 제안

## 현재 상황

### 실제 결과
- 총 거래: 502개 → 423개 (-15.7%)
- 총 수익: 192.90% → 197.27% (+2.3%)
- 승률: 51.0% → 52.7% (+1.7%p)
- 거래당 평균: 3,843원 → 4,664원 (+23.7%)

### 백테스트 vs 실제
| 지표 | 백테스트(9-10월) | 실제(전체) | 차이 |
|------|-----------------|-----------|------|
| 필터링 비율 | 22.0% | 15.7% | -6.3%p |
| 수익 증가 | +31.3% | +2.3% | -29.0%p |

**문제**: 9-10월 데이터로 만든 필터가 전체 기간에선 효과 감소

---

## 개선 방안

### 1. 롤링 윈도우 방식

**현재**: 9-10월 데이터로 고정된 11개 조합
**개선**: 최근 N개월 데이터로 지속 업데이트

```python
# 예: 매달 1일에 자동 업데이트
python update_filter_combinations.py --months 3 --min-trades 5
```

**장점**:
- 최신 시장 상황 반영
- 계절성 패턴 대응
- 과적합 방지

### 2. 조합 수 조정

**현재**: 11개 조합 제외 (15.7% 필터링)
**테스트해볼 것**:
- Top 5개만 제외 (더 보수적)
- Top 15개 제외 (더 공격적)

```python
# 손실 크기별 정렬 후 상위 N개 선택
negative_combos.nlargest(5, 'total_loss')
```

### 3. 최소 거래 수 기준 상향

**현재**: 1건 이상이면 포함
**개선**: 5~10건 이상일 때만 신뢰

```python
python update_filter_combinations.py --min-trades 10
```

**장점**:
- 통계적 신뢰도 향상
- 우연한 손실 조합 제외

### 4. 시기별 필터 세트

```python
# 월별로 다른 필터 적용
if month in [1, 2, 3]:  # 1분기
    use_filter_set_Q1()
elif month in [4, 5, 6]:  # 2분기
    use_filter_set_Q2()
# ...
```

**이유**:
- 계절마다 시장 특성 다름
- 월별 변동성 차이 존재

### 5. 가중치 기반 필터

**현재**: 조합 매칭되면 무조건 제외
**개선**: 손실 크기에 따라 확률적 제외

```python
def should_exclude_weighted(pattern, threshold=-10.0):
    """손실이 -10% 이상인 조합만 제외"""
    combo_loss = get_historical_loss(pattern)
    return combo_loss < threshold

# 또는 확률적으로
def should_exclude_probabilistic(pattern):
    """손실 크기에 비례하여 제외 확률 적용"""
    combo_loss = get_historical_loss(pattern)
    exclude_prob = min(abs(combo_loss) / 20.0, 1.0)  # -20% 손실 = 100% 제외
    return random.random() < exclude_prob
```

### 6. 승률과 수익률 복합 기준

**현재**: 총 수익만 고려
**개선**: 승률 + 총 수익 복합

```python
def calculate_score(combo_stats):
    """승률과 수익률을 모두 고려"""
    win_rate_score = (combo_stats['win_rate'] - 50) * 0.3  # 승률 가중치 30%
    profit_score = combo_stats['total_profit'] * 0.7  # 수익 가중치 70%
    return win_rate_score + profit_score

# 점수가 마이너스인 조합만 제외
negative_combos = [c for c in combos if calculate_score(c) < 0]
```

---

## 권장 접근법

### 단기 (1주일 내)

**A/B 테스트 실행**:
```python
# 절반은 필터 적용, 절반은 미적용
if hash(stock_code) % 2 == 0:
    apply_filter = True
else:
    apply_filter = False
```

1주일 후 결과 비교:
- 필터 적용 그룹 vs 미적용 그룹
- 실제 수익 차이 확인

### 중기 (1개월)

**필터 조합 수 최적화**:
```bash
# 5개, 10개, 15개, 20개 조합 테스트
for n in [5, 10, 15, 20]:
    python analyze_negative_profit_combinations.py --top-n $n
    # 각각의 예상 수익 비교
done
```

가장 좋은 조합 수 선택

### 장기 (3개월)

**롤링 윈도우 구현**:
```python
# 매달 1일에 자동 실행
# crontab: 0 0 1 * * python update_filter_combinations.py --months 3
```

최근 3개월 데이터로 지속 업데이트

---

## 실험 예시

### 실험 1: Top 5 vs Top 11 비교

```python
# Top 5만 제외
top5_combos = negative_combos.nsmallest(5, 'total_profit')
result_top5 = simulate_filter(df, top5_combos)

# Top 11 제외 (현재)
result_top11 = simulate_filter(df, negative_combos)

# 비교
print(f"Top 5:  수익 {result_top5['profit']:.2f}%, 거래 {result_top5['trades']}건")
print(f"Top 11: 수익 {result_top11['profit']:.2f}%, 거래 {result_top11['trades']}건")
```

### 실험 2: 최소 거래 수 영향

```python
for min_trades in [1, 3, 5, 10, 15]:
    combos = find_negative_combinations(df, min_trades=min_trades)
    result = simulate_filter(df, combos)
    print(f"최소 {min_trades}건: 조합 {len(combos)}개, 수익 {result['profit']:.2f}%")
```

### 실험 3: 시기별 차이

```python
# 월별 효과 분석
for month in range(9, 11):
    month_df = df[df['month'] == month]
    result = simulate_filter(month_df, negative_combos)
    print(f"{month}월: 수익 증가 {result['profit_increase']:.1f}%")
```

---

## 결론

현재 필터는 **거래당 평균 수익을 23.7% 증가**시키는 효과가 있습니다.

하지만 총 수익 증가가 2.3%로 작은 이유는:
1. 9-10월 데이터 편향
2. 필터 조합이 다른 시기엔 덜 효과적

**다음 스텝**:
1. 롤링 윈도우 방식으로 필터 주기적 업데이트
2. 조합 수 최적화 (5개 vs 11개 테스트)
3. 최소 거래 수 기준 상향 (1건 → 5건)

**유지 여부**:
- ✅ **유지 추천**: 거래당 수익 +23.7%, 승률 +1.7%p 개선
- ⚠️ **개선 필요**: 롤링 윈도우로 효과 극대화

---

**작성일**: 2025-11-06
