-- 2026-04-26: virtual_trading_records.strategy 컬럼은 이미 존재 (save_virtual_buy/sell 가 사용).
-- macd_cross 페이퍼 KPI 조회 가속을 위해 strategy 인덱스 추가.
-- Idempotent: IF NOT EXISTS 사용.
CREATE INDEX IF NOT EXISTS idx_vtr_strategy ON virtual_trading_records(strategy);
