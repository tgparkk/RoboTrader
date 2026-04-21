"""features: 원시 분봉을 받아 0~1 정규화된 피처 매트릭스를 생성한다.

look-ahead 방지 규칙:
- 모든 정규화는 `shift(1)` 후 past-only 윈도우에 적용한다.
- feature 계산에서 현재 봉의 close 를 쓰는 것은 허용 (진입 시점 정보 = 현재봉 close).
  단, 정규화 step 에서는 현재 값이 그 분포에 포함되면 안 된다.
"""
