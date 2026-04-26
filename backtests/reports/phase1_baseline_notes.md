# Phase 1 Baseline 재현 스모크 테스트 결과

**테스트 구간**: 20260101~20260228 (2개월)
**유니버스**: 005930, 000660, 035720
**초기자본**: 10,000,000

## 목적

엔진 end-to-end 실행 검증. Trial 837 Calmar 정확 재현이 아닌, 거래 생성 →
PnL 계산 → metrics 반환까지 에러 없이 완주하는지 확인.

## 결과

테스트는 `pytest -s tests/backtests/test_baseline_reproduction.py -v` 로 관찰.
구체 수치는 실행 시 stdout 에 출력됨.

- [ ] 거래 생성됨 (>0건) or 정상 skip
- [ ] final_equity > 0
- [ ] metrics dict 정상 반환
- [ ] 엔진 에러 없이 완주

## Phase 1 완료 체크리스트

- [x] Task 1: 스캐폴딩
- [x] Task 2: metrics.py
- [x] Task 3: execution_model.py
- [x] Task 4: capital_manager.py
- [x] Task 5: feature_audit.py (perturbation 방식)
- [x] Task 6: data_loader.py
- [x] Task 7: strategies/base.py
- [x] Task 8: engine.py
- [x] Task 9: baseline 어댑터 + 스모크 테스트

## Phase 2 로 이관할 이슈

1. **weighted_score 11개 피처 완전 포팅**: 현 어댑터는 4개만 구현. Trial 837
   Calmar ±20% 재현을 위해 모든 피처 (entry_pct, weights 등) 포팅 필요.
2. **TP/SL 체크 로직**: 엔진 exit_signal 에 current_price 기반 TP/SL 체크 훅 추가
   필요. 현재는 hold_days 만 체크.
3. **가변 bar-per-day**: 현 어댑터는 BARS_PER_TRADING_DAY=390 상수 가정. 실제
   데이터는 일별 bar 수 다름 → `trade_date` 기반 day counting 로 교체.
4. **시장 데이터 갭 처리**: minute_candles 가 공백인 날짜에 대한 fallback.

---

## Phase 2B-1 ~ 2B-3 완료 (2026-04-25)

### Phase 2B-1 — 브레이크아웃 (3개)
- ORB (Opening Range Breakout)
- 갭다운 역행 (Gap-Down Reversal)
- 갭업 추격 (Gap-Up Continuation)

### Phase 2B-2 — 평균회귀 (3개)
- VWAP 반등
- 볼린저 하단 반등
- RSI 과매도 반등

### Phase 2B-3 — 추세·거래량 (3개)
- 거래량 급증 추격 (Volume Surge Chase)
- 장중 눌림목 (20EMA Pullback)
- 종가 드리프트 (Closing Drift, overnight hold=1)

**전체 tests**: 138 passed + 2 skipped.

### 남은 classic 전략 (Phase 2B-4, 2C 예정)
- 상한가 따라잡기 (Phase 2B-4, 호가·유동성 제약 큼)
- Overnight swing 5개 (Phase 2C):
  - 종가매수→시가매도, 52주 신고가 돌파, 낙주 반등, 추세 follow-through, MACD 골든크로스

---

## Phase 2B-4 완료 (2026-04-25)

- [x] 상한가 따라잡기 (Limit-Up Chase)

전체 tests: 146 passed + 2 skipped.

**Classic intraday 10개 완성**: ORB / 갭다운역행 / 갭업추격 / VWAP반등 / BB하단 / RSI과매도 / 거래량급증 / 장중눌림목 / 종가드리프트 / 상한가추격.

**다음 (Phase 2C)**: Overnight swing 5개 (close_to_open, breakout_52w, post_drop_rebound, trend_followthrough, macd_cross).

---

## Phase 2C 완료 (2026-04-25)

- [x] close_to_open (강한 종가 매수, 익일 시가 매도)
- [x] breakout_52w (52주 신고가 돌파)
- [x] post_drop_rebound (낙주 반등)
- [x] trend_followthrough (5일 고점 follow-through)
- [x] macd_cross (MACD 골든크로스)

**전체 tests**: 177 passed + 2 skipped.

**Classic 카탈로그 16/16 완성** (15 신규 + 1 baseline weighted_score):
- Classic Intraday 10: ORB / 갭다운역행 / 갭업추격 / VWAP반등 / BB하단 / RSI과매도 / 거래량급증 / 장중눌림목 / 종가드리프트 / 상한가추격
- Classic Overnight 5: close_to_open / breakout_52w / post_drop_rebound / trend_followthrough / macd_cross
- Baseline 1: weighted_score_full (Trial 837)

**다음**: Phase 3 (Stage 1 coarse, 200 trials × 전략당).

---

## 엔진 속도 최적화 (2026-04-25)

### 진단
- 30 종목 × 22 일 (257K bars) 합성 데이터 벤치마크
- cProfile: `features.iloc[bar_idx]` 가 main loop 의 60%+ (15.7s 중 9.7s)
- 원인: pd.DataFrame `iloc[idx]` 는 새 Series 객체 생성 + Series indexing 누적 오버헤드

### 적용
- `backtests/common/feature_cache.py` 추가 — DataFrame → dict[col → np.ndarray] 캐시
- 캐시 위치: `features.attrs["_feature_cache_arrays"]` (pandas 객체 lifetime 보장, GC id 재사용 회피)
- 15 전략의 entry_signal 모두 변환: `arr = get_arrays(features); arr["col"][bar_idx]`

### 결과 (30 종목 × 22 일 벤치마크)
| 측정 | 변경 전 | 변경 후 | 속도 |
|------|---------|---------|------|
| 전체 합 (15 전략) | 72.0s | 20.6s | **3.5x** |
| 전략당 평균 | 4.8s | 1.4s | 3.4x |
| volume_surge | 6.23s | 1.12s | 5.6x |
| limit_up_chase | 6.58s | 1.33s | 5.0x |
| post_drop_rebound | 5.71s | 0.95s | 6.0x |
| macd_cross | 6.52s | 1.38s | 4.7x |

### Phase 3 추정 (200 trials × 15 strategies, 30종목 합성)
- 변경 전: 4.0h
- 변경 후: **1.1h** (sequential)
- + multiprocessing 8-core 병렬화 시 ~10분

### 회귀 검증
- 177 passed + 2 skipped (변경 전 동일)
