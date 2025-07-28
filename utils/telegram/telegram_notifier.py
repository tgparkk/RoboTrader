"""
텔레그램 알림 서비스
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

from utils.logger import setup_logger


class TelegramNotifier:
    """텔레그램 알림 서비스"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.logger = setup_logger(__name__)
        
        self.bot = Bot(token=bot_token)
        self.application = None
        self.is_initialized = False
        
        # 메시지 형식 템플릿
        self.templates = {
            'system_start': "🚀 *거래 시스템 시작*\n시간: {time}\n상태: 초기화 완료",
            'system_stop': "🛑 *거래 시스템 종료*\n시간: {time}\n상태: 정상 종료",
            'order_placed': "📝 *주문 실행*\n종목: {stock_name}({stock_code})\n구분: {order_type}\n수량: {quantity:,}주\n가격: {price:,}원\n주문ID: {order_id}",
            'order_filled': "✅ *주문 체결*\n종목: {stock_name}({stock_code})\n구분: {order_type}\n수량: {quantity:,}주\n가격: {price:,}원\n손익: {pnl:+,.0f}원",
            'order_cancelled': "❌ *주문 취소*\n종목: {stock_name}({stock_code})\n구분: {order_type}\n이유: {reason}",
            'signal_detected': "🔥 *매매 신호*\n종목: {stock_name}({stock_code})\n신호: {signal_type}\n가격: {price:,}원\n근거: {reason}",
            'position_update': "📊 *포지션 현황*\n보유: {position_count}종목\n평가: {total_value:,}원\n손익: {total_pnl:+,.0f}원 ({pnl_rate:+.2f}%)",
            'system_status': "📡 *시스템 상태*\n시간: {time}\n시장: {market_status}\n미체결: {pending_orders}건\n완료: {completed_orders}건\n데이터: 정상 수집",
            'error_alert': "⚠️ *시스템 오류*\n시간: {time}\n모듈: {module}\n오류: {error}",
            'daily_summary': "📈 *일일 거래 요약*\n날짜: {date}\n총 거래: {total_trades}회\n수익률: {return_rate:+.2f}%\n손익: {total_pnl:+,.0f}원"
        }
    
    async def initialize(self) -> bool:
        """텔레그램 봇 초기화"""
        try:
            self.logger.info("텔레그램 봇 초기화 시작...")
            
            # 봇 연결 테스트
            me = await self.bot.get_me()
            self.logger.info(f"봇 연결 성공: @{me.username}")
            
            # Application 생성
            self.application = Application.builder().token(self.bot_token).build()
            
            # 명령어 핸들러 등록
            self._register_commands()
            
            self.is_initialized = True
            self.logger.info("✅ 텔레그램 봇 초기화 완료")
            
            # 초기화 메시지 전송
            await self.send_system_start()
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 텔레그램 봇 초기화 실패: {e}")
            return False
    
    def _register_commands(self):
        """명령어 핸들러 등록"""
        handlers = [
            CommandHandler("status", self._cmd_status),
            CommandHandler("positions", self._cmd_positions),
            CommandHandler("orders", self._cmd_orders),
            CommandHandler("help", self._cmd_help),
            CommandHandler("stop", self._cmd_stop),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
    
    async def start_polling(self):
        """봇 폴링 시작 (명령어 수신)"""
        if not self.is_initialized:
            self.logger.error("봇이 초기화되지 않았습니다")
            return
        
        try:
            self.logger.info("텔레그램 봇 폴링 시작")
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            # 폴링이 계속 실행되도록 대기
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            self.logger.error(f"봇 폴링 오류: {e}")
        finally:
            try:
                if self.application and self.application.updater.running:
                    await self.application.updater.stop()
                if self.application:
                    await self.application.stop()
                    await self.application.shutdown()
            except Exception as shutdown_error:
                self.logger.error(f"봇 종료 중 오류: {shutdown_error}")
    
    async def send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """메시지 전송"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            return True
        except TelegramError as e:
            self.logger.error(f"텔레그램 메시지 전송 실패: {e}")
            return False
    
    # 시스템 이벤트 알림 메서드들
    async def send_system_start(self):
        """시스템 시작 알림"""
        message = self.templates['system_start'].format(
            time=datetime.now().strftime('%H:%M:%S')
        )
        await self.send_message(message)
    
    async def send_system_stop(self):
        """시스템 종료 알림"""
        message = self.templates['system_stop'].format(
            time=datetime.now().strftime('%H:%M:%S')
        )
        await self.send_message(message)
    
    async def send_order_placed(self, stock_code: str, stock_name: str, order_type: str, 
                              quantity: int, price: float, order_id: str):
        """주문 실행 알림"""
        message = self.templates['order_placed'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            order_type="매수" if order_type.lower() == "buy" else "매도",
            quantity=quantity,
            price=price,
            order_id=order_id
        )
        await self.send_message(message)
    
    async def send_order_filled(self, stock_code: str, stock_name: str, order_type: str,
                              quantity: int, price: float, pnl: float = 0):
        """주문 체결 알림"""
        message = self.templates['order_filled'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            order_type="매수" if order_type.lower() == "buy" else "매도",
            quantity=quantity,
            price=price,
            pnl=pnl
        )
        await self.send_message(message)
    
    async def send_order_cancelled(self, stock_code: str, stock_name: str, 
                                 order_type: str, reason: str):
        """주문 취소 알림"""
        message = self.templates['order_cancelled'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            order_type="매수" if order_type.lower() == "buy" else "매도",
            reason=reason
        )
        await self.send_message(message)
    
    async def send_signal_detected(self, stock_code: str, stock_name: str,
                                 signal_type: str, price: float, reason: str):
        """매매 신호 알림"""
        message = self.templates['signal_detected'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            signal_type=signal_type,
            price=price,
            reason=reason
        )
        await self.send_message(message)
    
    async def send_position_update(self, position_count: int, total_value: float,
                                 total_pnl: float, pnl_rate: float):
        """포지션 현황 알림"""
        message = self.templates['position_update'].format(
            position_count=position_count,
            total_value=total_value,
            total_pnl=total_pnl,
            pnl_rate=pnl_rate
        )
        await self.send_message(message)
    
    async def send_system_status(self, market_status: str, pending_orders: int, 
                               completed_orders: int):
        """시스템 상태 알림"""
        message = self.templates['system_status'].format(
            time=datetime.now().strftime('%H:%M:%S'),
            market_status=market_status,
            pending_orders=pending_orders,
            completed_orders=completed_orders
        )
        await self.send_message(message)
    
    async def send_error_alert(self, module: str, error: str):
        """오류 알림"""
        message = self.templates['error_alert'].format(
            time=datetime.now().strftime('%H:%M:%S'),
            module=module,
            error=str(error)[:100]  # 오류 메시지 길이 제한
        )
        await self.send_message(message)
    
    async def send_daily_summary(self, date: str, total_trades: int, 
                               return_rate: float, total_pnl: float):
        """일일 거래 요약"""
        message = self.templates['daily_summary'].format(
            date=date,
            total_trades=total_trades,
            return_rate=return_rate,
            total_pnl=total_pnl
        )
        await self.send_message(message)
    
    # 명령어 핸들러들
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """상태 조회 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        # TODO: 실제 시스템 상태 조회 로직 구현
        status_message = "📊 *시스템 상태*\n\n⏰ 시간: {}\n📈 시장: 장중\n🔄 상태: 정상 동작\n📊 데이터: 수집 중".format(
            datetime.now().strftime('%H:%M:%S')
        )
        
        await update.message.reply_text(status_message, parse_mode="Markdown")
    
    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """포지션 조회 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        # TODO: 실제 포지션 조회 로직 구현
        positions_message = "💼 *보유 포지션*\n\n현재 보유 중인 포지션이 없습니다."
        
        await update.message.reply_text(positions_message, parse_mode="Markdown")
    
    async def _cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """주문 현황 조회 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        # TODO: 실제 주문 현황 조회 로직 구현
        orders_message = "📋 *주문 현황*\n\n미체결 주문: 0건\n완료된 주문: 0건"
        
        await update.message.reply_text(orders_message, parse_mode="Markdown")
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """도움말 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        help_message = """
🤖 *거래 봇 명령어*

/status - 시스템 상태 조회
/positions - 보유 포지션 조회  
/orders - 주문 현황 조회
/help - 도움말 표시
/stop - 시스템 종료

📱 실시간 알림:
• 주문 실행/체결 시
• 매매 신호 감지 시
• 시스템 오류 발생 시
"""
        
        await update.message.reply_text(help_message, parse_mode="Markdown")
    
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """시스템 종료 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        await update.message.reply_text("⚠️ 시스템 종료 명령을 받았습니다. 안전하게 종료 중...")
        
        # TODO: 실제 시스템 종료 로직 구현
        # 이 부분은 메인 시스템과 연동 필요
    
    async def shutdown(self):
        """텔레그램 봇 종료"""
        try:
            await self.send_system_stop()
            
            if self.application:
                try:
                    if hasattr(self.application, 'updater') and self.application.updater.running:
                        await self.application.updater.stop()
                    await self.application.stop()
                    await self.application.shutdown()
                except Exception as app_error:
                    self.logger.error(f"Application 종료 중 오류: {app_error}")
            
            self.logger.info("텔레그램 봇 종료 완료")
            
        except Exception as e:
            self.logger.error(f"텔레그램 봇 종료 중 오류: {e}")


