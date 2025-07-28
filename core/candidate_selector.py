"""
매수 후보 종목 선정 모듈
"""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from .models import Stock, TradingConfig
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger
from utils.korean_time import now_kst


@dataclass
class CandidateStock:
    """후보 종목 정보"""
    code: str
    name: str
    market: str
    score: float  # 선정 점수
    reason: str   # 선정 이유


class CandidateSelector:
    """매수 후보 종목 선정기"""
    
    def __init__(self, config: TradingConfig, api_manager: KISAPIManager):
        self.config = config
        self.api_manager = api_manager
        self.logger = setup_logger(__name__)
        
        # stock_list.json 파일 경로
        self.stock_list_file = Path(__file__).parent.parent / "stock_list.json"
    
    async def select_daily_candidates(self, max_candidates: int = 5) -> List[CandidateStock]:
        """
        일일 매수 후보 종목 선정
        
        Args:
            max_candidates: 최대 후보 종목 수
            
        Returns:
            선정된 후보 종목 리스트
        """
        try:
            self.logger.info("🔍 일일 매수 후보 종목 선정 시작")
            
            # 1. 전체 종목 리스트 로드
            all_stocks = self._load_stock_list()
            if not all_stocks:
                self.logger.error("종목 리스트 로드 실패")
                return []
            
            self.logger.info(f"전체 종목 수: {len(all_stocks)}")
            
            # 2. 1차 필터링: 기본 조건 체크
            filtered_stocks = await self._apply_basic_filters(all_stocks)
            self.logger.info(f"1차 필터링 후: {len(filtered_stocks)}개 종목")
            
            # 3. 2차 필터링: 상세 분석
            candidate_stocks = await self._analyze_candidates(filtered_stocks)
            self.logger.info(f"2차 분석 후: {len(candidate_stocks)}개 후보")
            
            # 4. 점수 기준 정렬 및 상위 종목 선정
            candidate_stocks.sort(key=lambda x: x.score, reverse=True)
            selected_candidates = candidate_stocks[:max_candidates]
            
            self.logger.info(f"✅ 최종 선정된 후보 종목: {len(selected_candidates)}개")
            for candidate in selected_candidates:
                self.logger.info(f"  - {candidate.code}({candidate.name}): {candidate.score:.2f}점 - {candidate.reason}")
            
            return selected_candidates
            
        except Exception as e:
            self.logger.error(f"❌ 후보 종목 선정 실패: {e}")
            return []
    
    def _load_stock_list(self) -> List[Dict]:
        """stock_list.json 파일에서 종목 리스트 로드"""
        try:
            if not self.stock_list_file.exists():
                self.logger.error(f"종목 리스트 파일이 없습니다: {self.stock_list_file}")
                return []
            
            with open(self.stock_list_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return data.get('stocks', [])
            
        except Exception as e:
            self.logger.error(f"종목 리스트 로드 실패: {e}")
            return []
    
    async def _apply_basic_filters(self, stocks: List[Dict]) -> List[Dict]:
        """
        1차 기본 필터링
        - KOSPI 종목만
        - 우선주 제외 
        - 기타 기본 조건
        """
        filtered = []
        excluded_counts = {
            'non_kospi': 0,
            'preferred': 0,
            'convertible': 0,
            'etf': 0,
            'passed': 0
        }
        
        for stock in stocks:
            try:
                code = stock.get('code', '')
                name = stock.get('name', '')
                
                # KOSPI 종목만
                if stock.get('market') != 'KOSPI':
                    excluded_counts['non_kospi'] += 1
                    continue
                
                # 우선주 제외 (종목코드 끝자리가 5인 경우나 이름에 '우' 포함)
                if code.endswith('5') or '우' in name:
                    excluded_counts['preferred'] += 1
                    continue
                
                # 전환우선주 제외
                if '전환' in name:
                    excluded_counts['convertible'] += 1
                    continue
                
                # ETF, ETN 제외
                if any(keyword in name.upper() for keyword in ['ETF', 'ETN']):
                    excluded_counts['etf'] += 1
                    continue
                
                excluded_counts['passed'] += 1
                filtered.append(stock)
                
            except Exception as e:
                self.logger.warning(f"기본 필터링 중 오류 {stock}: {e}")
                continue
        
        self.logger.info(f"1차 필터링 결과: "
                        f"비KOSPI({excluded_counts['non_kospi']}), "
                        f"우선주({excluded_counts['preferred']}), "
                        f"전환({excluded_counts['convertible']}), "
                        f"ETF({excluded_counts['etf']}), "
                        f"통과({excluded_counts['passed']})")
        
        return filtered
    
    async def _analyze_candidates(self, stocks: List[Dict]) -> List[CandidateStock]:
        """
        2차 상세 분석 및 후보 종목 선정
        """
        candidates = []
        
        # 병렬 처리를 위해 배치 단위로 처리
        batch_size = 20
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i + batch_size]
            batch_candidates = await self._analyze_stock_batch(batch)
            candidates.extend(batch_candidates)
            
            # API 호출 제한 고려하여 잠시 대기
            if i + batch_size < len(stocks):
                await asyncio.sleep(1)
        
        return candidates
    
    async def _analyze_stock_batch(self, stocks: List[Dict]) -> List[CandidateStock]:
        """주식 배치 분석"""
        candidates = []
        
        for stock in stocks:
            try:
                candidate = await self._analyze_single_stock(stock)
                if candidate:
                    candidates.append(candidate)
                    
            except Exception as e:
                self.logger.warning(f"종목 분석 실패 {stock.get('code')}: {e}")
                continue
        
        return candidates
    
    async def _analyze_single_stock(self, stock: Dict) -> Optional[CandidateStock]:
        """
        개별 종목 분석
        
        선정 조건:
        A. 최고종가: 200일 중 최고종가
        B. Envelope(10,10) 종가가 상한선 이상  
        C. 시가 < 종가 (양봉)
        D. 전일 동시간 대비 거래량 비율 100% 이상
        E. 종가 > (고가+저가)/2 (중심가격 위)
        F. 5일 평균 거래대금 5000백만 이상
        G. NOT 전일 종가대비 시가 7% 이상 상승
        H. NOT 전일 종가대비 종가 10% 이상 상승  
        I. 시가대비 종가 3% 이상 상승
        """
        try:
            code = stock['code']
            name = stock['name']
            market = stock['market']
            
            self.logger.debug(f"📊 종목 분석 시작: {code}({name})")
            
            # 현재가 및 기본 정보 조회
            price_data = self.api_manager.get_current_price(code)
            if price_data is None:
                self.logger.debug(f"❌ {code}: 현재가 데이터 없음")
                return None
            
            # 일봉 데이터 조회 (200일)
            daily_data = self.api_manager.get_ohlcv_data(code, "D", 200)
            if daily_data is None:
                self.logger.debug(f"❌ {code}: 일봉 데이터 없음")
                return None
            
            # daily_data가 DataFrame인 경우 처리
            if hasattr(daily_data, 'empty'):
                if daily_data.empty or len(daily_data) < 200:
                    self.logger.debug(f"❌ {code}: 일봉 데이터 부족 ({len(daily_data)}일)")
                    return None
            elif len(daily_data) < 200:
                self.logger.debug(f"❌ {code}: 일봉 데이터 부족 ({len(daily_data)}일)")
                return None
            
            # 거래대금 조건 체크 (최소 50억)
            volume_amount = getattr(price_data, 'volume_amount', 0)
            if volume_amount == 0:
                # volume_amount가 없는 경우 volume * price로 계산
                current_volume = getattr(price_data, 'volume', 0)
                current_price = getattr(price_data, 'current_price', 0)
                volume_amount = current_volume * current_price
            
            if volume_amount < 5_000_000_000:
                self.logger.debug(f"❌ {code}: 거래대금 부족 ({volume_amount/1_000_000_000:.1f}억원)")
                return None
            
            self.logger.debug(f"✅ {code}: 기본 조건 통과 - 거래대금 {volume_amount/1_000_000_000:.1f}억원")
            
            # 조건 분석
            score = 0
            reasons = []
            
            # A. 200일 최고종가 체크
            today_close = price_data.current_price
            max_close_200d = max([data.close_price for data in daily_data])
            if today_close >= max_close_200d * 0.98:  # 98% 이상이면 신고가 근처
                score += 20
                reasons.append("200일 신고가 근처")
            
            # B. Envelope 상한선 돌파 체크
            if self._check_envelope_breakout(daily_data, today_close):
                score += 15
                reasons.append("Envelope 상한선 돌파")
            
            # C. 양봉 체크 (시가 < 종가)
            today_open = getattr(price_data, 'open_price', today_close)
            if today_close > today_open:
                score += 10
                reasons.append("양봉 형성")
            
            # D. 거래량 급증 체크 (평균 대비 3배 이상)
            recent_data = daily_data[-20:] if hasattr(daily_data, '__getitem__') else list(daily_data)[-20:]
            avg_volume = sum([data.volume for data in recent_data]) / len(recent_data)
            current_volume = getattr(price_data, 'volume', 0)
            if current_volume >= avg_volume * 3:
                score += 25
                reasons.append("거래량 3배 급증")
            elif current_volume >= avg_volume * 2:
                score += 15
                reasons.append("거래량 2배 증가")
            
            # E. 중심가격 위 체크
            high_price = getattr(price_data, 'high_price', today_close)
            low_price = getattr(price_data, 'low_price', today_close)
            mid_price = (high_price + low_price) / 2
            if today_close > mid_price:
                score += 10
                reasons.append("중심가격 상회")
            
            # F. 5일 평균 거래대금 체크 (50억 이상)
            recent_5d = daily_data[-5:] if hasattr(daily_data, '__getitem__') else list(daily_data)[-5:]
            avg_amount_5d = sum([data.volume * data.close_price for data in recent_5d]) / len(recent_5d)
            if avg_amount_5d >= 5_000_000_000:
                score += 15
                reasons.append("충분한 거래대금")
            
            # G, H. 급등주 제외 조건
            data_len = len(daily_data) if hasattr(daily_data, '__len__') else len(list(daily_data))
            if data_len >= 2:
                data_list = daily_data if hasattr(daily_data, '__getitem__') else list(daily_data)
                prev_close = data_list[-2].close_price
                open_change = (today_open - prev_close) / prev_close if prev_close > 0 else 0
                close_change = (today_close - prev_close) / prev_close if prev_close > 0 else 0
                
                # 시가 7% 이상 갭상승 시 제외
                if open_change >= 0.07:
                    self.logger.debug(f"❌ {code}: 시가 갭상승 제외 ({open_change:.1%})")
                    return None
                
                # 종가 10% 이상 상승 시 제외  
                if close_change >= 0.10:
                    self.logger.debug(f"❌ {code}: 급등주 제외 ({close_change:.1%})")
                    return None
            
            # I. 시가대비 종가 3% 이상 상승
            intraday_change = (today_close - today_open) / today_open if today_open > 0 else 0
            if intraday_change >= 0.03:
                score += 20
                reasons.append("당일 3% 이상 상승")
            
            self.logger.debug(f"📊 {code}: 최종 점수 {score}점 - {', '.join(reasons) if reasons else '조건 미충족'}")
            
            # 최소 점수 기준
            if score < 50:
                self.logger.debug(f"❌ {code}: 최소 점수 미달 ({score}점 < 50점)")
                return None
            
            return CandidateStock(
                code=code,
                name=name,
                market=market,
                score=score,
                reason=", ".join(reasons)
            )
            
        except Exception as e:
            self.logger.warning(f"종목 분석 실패 {stock.get('code')}: {e}")
            return None
    
    def _check_envelope_breakout(self, daily_data, current_price: float) -> bool:
        """Envelope(10, 10%) 상한선 돌파 체크"""
        try:
            data_len = len(daily_data) if hasattr(daily_data, '__len__') else len(list(daily_data))
            if data_len < 10:
                return False
            
            # 최근 10일 평균
            recent_10d = daily_data[-10:] if hasattr(daily_data, '__getitem__') else list(daily_data)[-10:]
            ma10 = sum([data.close_price for data in recent_10d]) / len(recent_10d)
            
            # Envelope 상한선 (MA + 10%)
            upper_envelope = ma10 * 1.10
            
            return current_price >= upper_envelope
            
        except Exception:
            return False
    
    def update_candidate_stocks_in_config(self, candidates: List[CandidateStock]):
        """선정된 후보 종목을 데이터 컬렉터에 업데이트"""
        try:
            # 후보 종목 코드 리스트 생성
            candidate_codes = [candidate.code for candidate in candidates]
            
            # 설정에 업데이트
            self.config.data_collection.candidate_stocks = candidate_codes
            
            self.logger.info(f"후보 종목 설정 업데이트 완료: {len(candidate_codes)}개")
            
        except Exception as e:
            self.logger.error(f"후보 종목 설정 업데이트 실패: {e}")