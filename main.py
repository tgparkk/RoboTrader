"""
주식 단타 거래 시스템 메인 실행 파일
"""
import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from core.models import TradingConfig
from core.data_collector import RealTimeDataCollector
from core.order_manager import OrderManager
from core.telegram_integration import TelegramIntegration
from core.candidate_selector import CandidateSelector
from api.kis_api_manager import KISAPIManager
from config.settings import load_trading_config
from utils.logger import setup_logger
from utils.korean_time import now_kst, get_market_status, is_market_open


class DayTradingBot:
    """주식 단타 거래 봇"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.is_running = False
        
        # 설정 초기화
        self.config = self._load_config()
        
        # 핵심 모듈 초기화
        self.api_manager = KISAPIManager()
        self.telegram = TelegramIntegration(trading_bot=self)
        self.data_collector = RealTimeDataCollector(self.config, self.api_manager)
        self.order_manager = OrderManager(self.config, self.api_manager, self.telegram)
        self.candidate_selector = CandidateSelector(self.config, self.api_manager)
        
        # 신호 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _load_config(self) -> TradingConfig:
        """거래 설정 로드"""
        config = load_trading_config()
        self.logger.info(f"거래 설정 로드 완료: 후보종목 {len(config.data_collection.candidate_stocks)}개")
        return config
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러 (Ctrl+C 등)"""
        self.logger.info(f"종료 신호 수신: {signum}")
        self.is_running = False
    
    async def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            self.logger.info("🚀 주식 단타 거래 시스템 초기화 시작")
            
            # 1. API 초기화
            self.logger.info("📡 API 매니저 초기화 시작...")
            if not self.api_manager.initialize():
                self.logger.error("❌ API 초기화 실패")
                return False
            self.logger.info("✅ API 매니저 초기화 완료")
            
            # 2. 시장 상태 확인
            market_status = get_market_status()
            self.logger.info(f"📊 현재 시장 상태: {market_status}")
            
            # 3. 텔레그램 초기화
            await self.telegram.initialize()
            
            # 4. 후보 종목 설정 (동적 선정을 위해 초기화만 수행)
            # TODO: 매일 장전 동적으로 후보 종목 선정 로직 구현
            
            self.logger.info("✅ 시스템 초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 초기화 실패: {e}")
            return False
    
    async def run_daily_cycle(self):
        """일일 거래 사이클 실행"""
        try:
            self.is_running = True
            self.logger.info("📈 일일 거래 사이클 시작")
            
            # 병렬 실행할 태스크들
            tasks = [
                self._data_collection_task(),
                self._order_monitoring_task(),
                self._trading_decision_task(),
                self._system_monitoring_task(),
                self._telegram_task()
            ]
            
            # 모든 태스크 실행
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 일일 거래 사이클 실행 중 오류: {e}")
        finally:
            await self.shutdown()
    
    async def _data_collection_task(self):
        """데이터 수집 태스크"""
        try:
            self.logger.info("📊 데이터 수집 태스크 시작")
            await self.data_collector.start_collection()
        except Exception as e:
            self.logger.error(f"❌ 데이터 수집 태스크 오류: {e}")
    
    async def _order_monitoring_task(self):
        """주문 모니터링 태스크"""
        try:
            self.logger.info("🔍 주문 모니터링 태스크 시작")
            await self.order_manager.start_monitoring()
        except Exception as e:
            self.logger.error(f"❌ 주문 모니터링 태스크 오류: {e}")
    
    async def _trading_decision_task(self):
        """매매 의사결정 태스크"""
        try:
            self.logger.info("🤖 매매 의사결정 태스크 시작")
            
            while self.is_running:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                # 현재는 기본 로직만 구현 (전략은 나중에 추가)
                await self._simple_trading_logic()
                await asyncio.sleep(60)  # 1분마다 체크
                
        except Exception as e:
            self.logger.error(f"❌ 매매 의사결정 태스크 오류: {e}")
    
    async def _simple_trading_logic(self):
        """간단한 매매 로직 (예시)"""
        try:
            # 후보 종목들의 최신 데이터 확인
            candidate_stocks = self.data_collector.get_candidate_stocks()
            
            for stock in candidate_stocks:
                if len(stock.ohlcv_data) < 5:  # 최소 5개 데이터 필요
                    continue
                
                # 간단한 예시: 최근 5분간 상승률 체크
                recent_data = stock.get_recent_ohlcv(5)
                if len(recent_data) >= 2:
                    price_change = (recent_data[-1].close_price - recent_data[0].close_price) / recent_data[0].close_price
                    
                    # 1% 이상 상승 시 매수 신호 (예시)
                    if price_change > 0.01 and stock.position.value == "none":
                        self.logger.info(f"🔥 매수 신호 감지: {stock.code} - 상승률: {price_change:.2%}")
                        
                        # 텔레그램 신호 알림
                        await self.telegram.notify_signal_detected({
                            'stock_code': stock.code,
                            'stock_name': stock.name,
                            'signal_type': '매수',
                            'price': recent_data[-1].close_price,
                            'reason': f'{price_change:.2%} 상승'
                        })
                        
                        # TODO: 실제 매수 로직 구현
                        
        except Exception as e:
            self.logger.error(f"❌ 매매 로직 실행 오류: {e}")
    
    async def _telegram_task(self):
        """텔레그램 태스크"""
        try:
            self.logger.info("📱 텔레그램 태스크 시작")
            
            # 텔레그램 봇 폴링과 주기적 상태 알림을 병렬 실행
            telegram_tasks = [
                self.telegram.start_telegram_bot(),
                self.telegram.periodic_status_task()
            ]
            
            await asyncio.gather(*telegram_tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 텔레그램 태스크 오류: {e}")
    
    async def _system_monitoring_task(self):
        """시스템 모니터링 태스크"""
        try:
            self.logger.info("📡 시스템 모니터링 태스크 시작")
            
            last_api_refresh = now_kst()
            last_market_check = now_kst()
            
            while self.is_running:
                current_time = now_kst()
                
                # API 24시간마다 재초기화
                if (current_time - last_api_refresh).total_seconds() >= 86400:  # 24시간
                    await self._refresh_api()
                    last_api_refresh = current_time
                
                # 매일 오전 8시에 시장 상태 및 후보 종목 갱신
                if (current_time.hour == 8 and current_time.minute == 0 and 
                    (current_time - last_market_check).total_seconds() >= 3600):  # 1시간 간격으로 체크
                    await self._daily_market_update()
                    last_market_check = current_time
                
                # 30분마다 시스템 상태 로그
                await asyncio.sleep(1800)
                await self._log_system_status()
                
        except Exception as e:
            self.logger.error(f"❌ 시스템 모니터링 태스크 오류: {e}")
            # 텔레그램 오류 알림
            await self.telegram.notify_error("SystemMonitoring", e)
    
    async def _log_system_status(self):
        """시스템 상태 로깅"""
        try:
            current_time = now_kst()
            market_status = get_market_status()
            
            # 주문 요약
            order_summary = self.order_manager.get_order_summary()
            
            # 데이터 수집 상태
            candidate_stocks = self.data_collector.get_candidate_stocks()
            data_counts = {stock.code: len(stock.ohlcv_data) for stock in candidate_stocks}
            
            self.logger.info(
                f"📊 시스템 상태 [{current_time.strftime('%H:%M:%S')}]\n"
                f"  - 시장 상태: {market_status}\n"
                f"  - 미체결 주문: {order_summary['pending_count']}건\n"
                f"  - 완료 주문: {order_summary['completed_count']}건\n"
                f"  - 데이터 수집: {data_counts}"
            )
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 상태 로깅 오류: {e}")
    
    async def _refresh_api(self):
        """API 재초기화"""
        try:
            self.logger.info("🔄 API 24시간 주기 재초기화 시작")
            
            # API 매니저 재초기화
            if not self.api_manager.initialize():
                self.logger.error("❌ API 재초기화 실패")
                await self.telegram.notify_error("API Refresh", "API 재초기화 실패")
                return False
                
            self.logger.info("✅ API 재초기화 완료")
            await self.telegram.notify_system_status("API 재초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ API 재초기화 오류: {e}")
            await self.telegram.notify_error("API Refresh", e)
            return False
    
    async def _daily_market_update(self):
        """일일 시장 상태 및 후보 종목 갱신"""
        try:
            self.logger.info("📊 일일 시장 정보 갱신 시작")
            
            # 시장 상태 갱신
            market_status = get_market_status()
            self.logger.info(f"📈 시장 상태 갱신: {market_status}")
            
            # 후보 종목 동적 선정
            self.logger.info("🔍 후보 종목 동적 선정 시작")
            candidates = await self.candidate_selector.select_daily_candidates(max_candidates=5)
            
            if candidates:
                # 후보 종목을 설정에 업데이트
                self.candidate_selector.update_candidate_stocks_in_config(candidates)
                
                # 데이터 컬렉터에 새로운 후보 종목 추가
                for candidate in candidates:
                    self.data_collector.add_candidate_stock(candidate.code, candidate.name)
                
                # 텔레그램 알림
                candidate_info = "\n".join([
                    f"  - {c.code}({c.name}): {c.score:.1f}점"
                    for c in candidates
                ])
                await self.telegram.notify_system_status(
                    f"🎯 일일 후보 종목 선정 완료:\n{candidate_info}"
                )
                
                self.logger.info(f"✅ 후보 종목 선정 완료: {len(candidates)}개")
            else:
                self.logger.warning("⚠️ 선정된 후보 종목이 없습니다")
                await self.telegram.notify_system_status("⚠️ 오늘은 선정된 후보 종목이 없습니다")
            
            await self.telegram.notify_system_status(f"일일 시장 정보 갱신 완료 - 시장 상태: {market_status}")
            
        except Exception as e:
            self.logger.error(f"❌ 일일 시장 정보 갱신 오류: {e}")
            await self.telegram.notify_error("Daily Market Update", e)

    async def shutdown(self):
        """시스템 종료"""
        try:
            self.logger.info("🛑 시스템 종료 시작")
            
            # 데이터 수집 중단
            self.data_collector.stop_collection()
            
            # 주문 모니터링 중단
            self.order_manager.stop_monitoring()
            
            # 텔레그램 통합 종료
            await self.telegram.shutdown()
            
            # API 매니저 종료
            self.api_manager.shutdown()
            
            self.logger.info("✅ 시스템 종료 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 종료 중 오류: {e}")


async def main():
    """메인 함수"""
    bot = DayTradingBot()
    
    # 시스템 초기화
    if not await bot.initialize():
        sys.exit(1)
    
    # 일일 거래 사이클 실행
    await bot.run_daily_cycle()


if __name__ == "__main__":
    try:
        # 로그 디렉토리 생성
        Path("logs").mkdir(exist_ok=True)
        
        # 메인 실행
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"시스템 오류: {e}")
        sys.exit(1)