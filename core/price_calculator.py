"""
가격 계산 유틸리티 클래스
매수/매도 가격 계산 관련 로직을 담당
"""
import pandas as pd
from typing import Optional, Tuple
from utils.logger import setup_logger


class PriceCalculator:
    """가격 계산 전용 클래스"""
    
    @staticmethod
    def calculate_three_fifths_price(data_3min: pd.DataFrame, logger=None) -> Tuple[Optional[float], Optional[float]]:
        """
        신호 캔들의 4/5 가격 계산 (개선된 방식)
        분석 결과에 따라 3/5가에서 4/5가로 변경하여 체결률 향상
        
        Args:
            data_3min: 3분봉 데이터
            logger: 로거 (옵션)
            
        Returns:
            tuple: (4/5 가격, 신호 캔들 저가) 또는 (None, None)
        """
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern
            
            if data_3min is None or data_3min.empty:
                return None, None
                
            # 신호 계산 (main.py, signal_replay.py와 동일한 설정)
            signals_3m = PullbackCandlePattern.generate_trading_signals(
                data_3min,
                enable_candle_shrink_expand=False,
                enable_divergence_precondition=False,
                enable_overhead_supply_filter=True,
                use_improved_logic=True,
                candle_expand_multiplier=1.10,
                overhead_lookback=10,
                overhead_threshold_hits=2,
            )
            
            if signals_3m is None or signals_3m.empty:
                return None, None
                
            # 매수 신호 컬럼들 확인
            buy_cols = []
            if 'buy_bisector_recovery' in signals_3m.columns:
                buy_cols.append('buy_bisector_recovery')
            if 'buy_pullback_pattern' in signals_3m.columns:
                buy_cols.append('buy_pullback_pattern')
                
            # 가장 최근 신호 인덱스 찾기
            last_idx = None
            for col in buy_cols:
                true_indices = signals_3m.index[signals_3m[col] == True].tolist()
                if true_indices:
                    candidate = true_indices[-1]
                    last_idx = candidate if last_idx is None else max(last_idx, candidate)
                    
            if last_idx is not None and 0 <= last_idx < len(data_3min):
                sig_high = float(data_3min['high'].iloc[last_idx])
                sig_low = float(data_3min['low'].iloc[last_idx])
                sig_volume = float(data_3min['volume'].iloc[last_idx])
                
                # 기본 4/5 구간 가격 (80% 지점) 계산
                base_price = sig_low + (sig_high - sig_low) * 0.8
                
                # 조건별 차등 가격 적용
                final_price = PriceCalculator._apply_conditional_pricing(
                    base_price, sig_high, sig_low, sig_volume, data_3min, last_idx, logger
                )
                
                if final_price > 0 and sig_low <= final_price <= sig_high:
                    if logger:
                        logger.debug(f"📊 4/5가 계산: {final_price:,.0f}원 (H:{sig_high:,.0f}, L:{sig_low:,.0f})")
                    return final_price, sig_low
                    
            return None, None
            
        except Exception as e:
            if logger:
                logger.debug(f"4/5가 계산 오류: {e}")
            return None, None
    
    @staticmethod
    def _apply_conditional_pricing(base_price: float, sig_high: float, sig_low: float, 
                                 sig_volume: float, data_3min: pd.DataFrame, 
                                 last_idx: int, logger=None) -> float:
        """
        조건별 차등 가격 적용 (거래대금 기준)
        
        Args:
            base_price: 기본 4/5가 (80% 지점)
            sig_high: 신호 캔들 고가
            sig_low: 신호 캔들 저가
            sig_volume: 신호 캔들 거래량
            data_3min: 3분봉 데이터
            last_idx: 신호 인덱스
            logger: 로거
            
        Returns:
            float: 최종 매수가격
            
        거래대금 구간:
        - 대형주(20억+): 최소 4/5가(80%)
        - 중대형주(10억+): 최소 3.5/5가(75%)
        - 중형주(5억+): 최소 3.5/5가(70%)
        - 소형주(1억+): 최소 3.25/5가(65%)
        - 초소형주(1억-): 기본 비율 유지
        """
        try:
            from datetime import datetime
            
            final_price = base_price
            price_ratio = 0.8  # 기본 4/5가
            
            # 거래대금 계산 (거래량 * 평균가격)
            avg_price = (sig_high + sig_low) / 2
            trading_amount = sig_volume * avg_price
            
            # 1. 가격대별 기본 비율 설정
            if sig_high < 5000:  # 5천원 미만
                base_ratio = 0.8  # 4/5가
            elif sig_high < 10000:  # 5천-1만원
                base_ratio = 0.75  # 3.5/5가
            elif sig_high < 20000:  # 1만-2만원
                base_ratio = 0.7   # 3.5/5가
            elif sig_high < 50000:  # 2만-5만원
                base_ratio = 0.8   # 4/5가
            else:  # 5만원 이상
                base_ratio = 0.6   # 3/5가 (고가격대는 원래대로)
            
            # 2. 거래대금별 차등 적용
            if trading_amount >= 2000000000:  # 초고거래대금 (20억 이상) - 대형주
                price_ratio = max(base_ratio, 0.8)  # 최소 4/5가
            elif trading_amount >= 1000000000:  # 고거래대금 (10억-20억) - 중대형주
                price_ratio = max(base_ratio, 0.75)  # 최소 3.5/5가
            elif trading_amount >= 500000000:  # 중거래대금 (5억-10억) - 중형주
                price_ratio = max(base_ratio, 0.7)  # 최소 3.5/5가
            elif trading_amount >= 100000000:  # 저거래대금 (1억-5억) - 소형주
                price_ratio = max(base_ratio, 0.65)  # 최소 3.25/5가
            else:  # 초저거래대금 (1억 미만) - 초소형주
                price_ratio = base_ratio  # 기본 비율 유지
            
            # 3. 시간대별 차등 적용
            if last_idx < len(data_3min):
                signal_time = data_3min['datetime'].iloc[last_idx]
                if hasattr(signal_time, 'hour'):
                    hour = signal_time.hour
                    if 11 <= hour <= 13:  # 11시-13시 (저승률 시간대)
                        price_ratio = max(price_ratio, 0.8)  # 최소 4/5가
                    elif hour >= 14:  # 14시 이후 (고승률 시간대)
                        price_ratio = min(price_ratio, 0.7)  # 최대 3.5/5가
            
            # 최종 가격 계산
            final_price = sig_low + (sig_high - sig_low) * price_ratio
            
            if logger:
                # 거래대금 구간 분류
                if trading_amount >= 2000000000:
                    amount_category = "대형주(20억+)"
                elif trading_amount >= 1000000000:
                    amount_category = "중대형주(10억+)"
                elif trading_amount >= 500000000:
                    amount_category = "중형주(5억+)"
                elif trading_amount >= 100000000:
                    amount_category = "소형주(1억+)"
                else:
                    amount_category = "초소형주(1억-)"
                
                logger.debug(f"📊 조건별 가격 적용: {price_ratio:.2f} (기본: {base_ratio:.2f}) → {final_price:,.0f}원 "
                           f"({amount_category}, 거래대금: {trading_amount:,.0f}원)")
            
            return final_price
            
        except Exception as e:
            if logger:
                logger.debug(f"조건별 가격 적용 오류: {e}")
            return base_price
    
    @staticmethod
    def calculate_stop_loss_price(buy_price: float, target_profit_rate: float = 0.03) -> float:
        """
        손절가 계산 (손익비 2:1 적용)
        
        Args:
            buy_price: 매수가
            target_profit_rate: 목표 수익률 (기본 1.5%)
            
        Returns:
            float: 손절가
        """
        stop_loss_rate = target_profit_rate / 2.0  # 손익비 2:1
        return buy_price * (1.0 - stop_loss_rate)
    
    @staticmethod
    def calculate_profit_price(buy_price: float, target_profit_rate: float = 0.03) -> float:
        """
        익절가 계산
        
        Args:
            buy_price: 매수가
            target_profit_rate: 목표 수익률 (기본 1.5%)
            
        Returns:
            float: 익절가
        """
        return buy_price * (1.0 + target_profit_rate)
    
    @staticmethod
    def get_target_profit_rate_from_signal(buy_reason: str) -> float:
        """
        신호 강도에 따른 목표 수익률 반환
        
        Args:
            buy_reason: 매수 사유
            
        Returns:
            float: 목표 수익률
        """
        if 'strong' in buy_reason.lower():
            return 0.025  # 최고신호: 2.5%
        elif 'cautious' in buy_reason.lower():
            return 0.02   # 중간신호: 2.0%
        else:
            return 0.015  # 기본신호: 1.5%