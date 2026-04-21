"""전역 상수: 날짜 분할, 거래비용, 자본, 시드, universe 기준 등.

플랜 참조: C:\\Users\\sttgp\\.claude\\plans\\500-1-1-distributed-hearth.md
"""
from __future__ import annotations

from pathlib import Path

# === 실험 기간 ===
# minute_candles 실제 커버리지: 2025-02-24 ~ 2026-04-17
DATA_START = "20250224"
DATA_END = "20260417"

# 약 13.7개월 중 8:4 비율 → train 9개월 / test 5개월 근사
# (영업일 기준이 아니라 달력일 근사. 실제 분할일자는 SQL에서 거래일만 선별 후 2/3 지점을 기준.)
TRAIN_END = "20251123"
TEST_START = "20251124"
TEST_END = DATA_END

# === Universe 기준 ===
# "260일+ 풀커버" — 총 ~270 거래일 중 96%+ 커버하는 종목만
MIN_TRADING_DAYS = 260

# === 거래비용 ===
# 편도 비용 = 수수료(0.015%) + 증권거래세·농특세(0.18%) + 슬리피지(0.05%) + 유관비용 ≈ 0.28%
# 매도시 세금이 부과되므로 편도 평균 0.28%로 단순화 (왕복 ~0.56%)
COST_ONE_WAY_PCT = 0.28

# 민감도 테스트용 (최종 검증 시 robust 체크)
COST_SENSITIVITY_PCTS = (0.28, 0.35, 0.45)

# === 자본/포지션 ===
INITIAL_CAPITAL = 100_000_000  # 1억원
POSITION_SIZE_KRW = 10_000_000  # 건당 고정 1,000만원

# === 동시 보유 범위 (Optuna 탐색 범위) ===
MAX_POSITIONS_MIN = 3
MAX_POSITIONS_MAX = 10

# === 홀딩 상한 후보 ===
MAX_HOLDING_DAYS_CHOICES = (3, 5)

# === 재현성 ===
SEED = 42

# === 병렬 ===
N_JOBS = 4

# === 경로 ===
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # D:\GIT\RoboTrader
RESEARCH_ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = RESEARCH_ROOT / "artifacts"
FEATURES_CACHE_DIR = ARTIFACTS_DIR / "features"
PHASE_A_DIR = ARTIFACTS_DIR / "phase_a"
PHASE_B_DIR = ARTIFACTS_DIR / "phase_b"


def ensure_artifact_dirs() -> None:
    """아티팩트 디렉토리 생성 (최초 1회)."""
    for p in (ARTIFACTS_DIR, FEATURES_CACHE_DIR, PHASE_A_DIR, PHASE_B_DIR):
        p.mkdir(parents=True, exist_ok=True)
