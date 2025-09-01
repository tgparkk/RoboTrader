"""
실시간 데이터 로거 - 장중 _update_intraday_data에서 수집한 데이터를 종목별 파일로 저장
"""
import os
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd
from pathlib import Path
import threading

from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open


class RealtimeDataLogger:
    """실시간 데이터를 종목별 파일로 저장하는 로거"""
    
    def __init__(self, base_dir: str = "realtime_data"):
        """
        초기화
        
        Args:
            base_dir: 데이터 저장 기본 디렉토리
        """
        self.logger = setup_logger(__name__)
        self.base_dir = Path(base_dir)
        
        # 날짜별 디렉토리 생성
        today_str = now_kst().strftime("%Y%m%d")
        self.today_dir = self.base_dir / today_str
        self.today_dir.mkdir(parents=True, exist_ok=True)
        
        # 동기화용 락
        self._lock = threading.RLock()
        
        # 종목별 파일 핸들 캐시
        self._file_handles: Dict[str, Any] = {}
        
        self.logger.info(f"📄 실시간 데이터 로거 초기화: {self.today_dir}")
    
    def log_minute_data(self, stock_code: str, stock_name: str, minute_data: pd.DataFrame):
        """
        분봉 데이터 로깅
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            minute_data: 분봉 데이터 (1개 이상)
        """
        try:
            if minute_data is None or minute_data.empty:
                return
            
            with self._lock:
                # 파일명 생성: YYYYMMDD_종목코드_종목명_minute.txt
                filename = f"{now_kst().strftime('%Y%m%d')}_{stock_code}_{stock_name}_minute.txt"
                file_path = self.today_dir / filename
                
                # 데이터를 한 줄씩 포맷하여 저장
                with open(file_path, 'a', encoding='utf-8') as f:
                    for _, row in minute_data.iterrows():
                        timestamp = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                        
                        # 분봉 데이터 포맷
                        if 'time' in row:
                            candle_time = str(row['time']).zfill(6)  # HHMMSS
                        elif 'datetime' in row:
                            candle_time = pd.Timestamp(row['datetime']).strftime('%H%M%S')
                        else:
                            candle_time = 'N/A'
                        
                        line = (
                            f"{timestamp} | "
                            f"종목={stock_code} | "
                            f"캔들시간={candle_time} | "
                            f"시가={row.get('open', 0):,} | "
                            f"고가={row.get('high', 0):,} | "
                            f"저가={row.get('low', 0):,} | "
                            f"종가={row.get('close', 0):,} | "
                            f"거래량={row.get('volume', 0):,}\n"
                        )
                        f.write(line)
                
                self.logger.debug(f"📄 {stock_code} 분봉 데이터 저장: {len(minute_data)}건 -> {filename}")
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 분봉 데이터 로깅 오류: {e}")
    
    def log_current_price(self, stock_code: str, stock_name: str, price_data: Dict[str, Any]):
        """
        현재가 데이터 로깅
        
        Args:
            stock_code: 종목코드 
            stock_name: 종목명
            price_data: 현재가 정보
        """
        try:
            if not price_data:
                return
            
            with self._lock:
                # 파일명 생성: YYYYMMDD_종목코드_종목명_price.txt
                filename = f"{now_kst().strftime('%Y%m%d')}_{stock_code}_{stock_name}_price.txt"
                file_path = self.today_dir / filename
                
                timestamp = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                
                line = (
                    f"{timestamp} | "
                    f"종목={stock_code} | "
                    f"현재가={price_data.get('current_price', 0):,} | "
                    f"전일대비={price_data.get('change_rate', 0):+.2f}% | "
                    f"거래량={price_data.get('volume', 0):,} | "
                    f"고가={price_data.get('high_price', 0):,} | "
                    f"저가={price_data.get('low_price', 0):,} | "
                    f"시가={price_data.get('open_price', 0):,}\n"
                )
                
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(line)
                
                #self.logger.debug(f"📄 {stock_code} 현재가 데이터 저장 -> {filename}")
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 현재가 데이터 로깅 오류: {e}")
    
    def log_trading_signal(self, stock_code: str, stock_name: str, signal_data: Dict[str, Any]):
        """
        매매신호 데이터 로깅
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명  
            signal_data: 신호 정보
        """
        try:
            if not signal_data:
                return
            
            with self._lock:
                # 파일명 생성: YYYYMMDD_종목코드_종목명_signals.txt
                filename = f"{now_kst().strftime('%Y%m%d')}_{stock_code}_{stock_name}_signals.txt"
                file_path = self.today_dir / filename
                
                timestamp = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                
                line = (
                    f"{timestamp} | "
                    f"종목={stock_code} | "
                    f"매수신호={signal_data.get('buy_signal', False)} | "
                    f"신호타입={signal_data.get('signal_type', '')} | "
                    f"신뢰도={signal_data.get('confidence', 0):.1f}% | "
                    f"사유={signal_data.get('buy_reason', '')} | "
                    f"데이터량={signal_data.get('data_length', 0)}개 | "
                    f"목표수익률={signal_data.get('target_profit', 0)*100:.1f}%\n"
                )
                
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(line)
                
                self.logger.debug(f"📄 {stock_code} 매매신호 저장 -> {filename}")
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 매매신호 로깅 오류: {e}")
    
    def log_combined_data(self, stock_code: str, stock_name: str, 
                         minute_data: Optional[pd.DataFrame] = None,
                         price_data: Optional[Dict[str, Any]] = None,
                         signal_data: Optional[Dict[str, Any]] = None):
        """
        통합 데이터 로깅 (분봉 + 현재가 + 신호)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            minute_data: 분봉 데이터
            price_data: 현재가 데이터
            signal_data: 신호 데이터
        """
        try:
            # 각 데이터 타입별로 개별 로깅
            if minute_data is not None and not minute_data.empty:
                self.log_minute_data(stock_code, stock_name, minute_data)
            
            if price_data:
                self.log_current_price(stock_code, stock_name, price_data)
            
            if signal_data:
                self.log_trading_signal(stock_code, stock_name, signal_data)
            
            # 통합 로그 파일도 생성
            with self._lock:
                filename = f"{now_kst().strftime('%Y%m%d')}_{stock_code}_{stock_name}_combined.txt"
                file_path = self.today_dir / filename
                
                timestamp = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                
                # 통합 정보 요약
                summary_parts = []
                if minute_data is not None and not minute_data.empty:
                    last_candle = minute_data.iloc[-1]
                    summary_parts.append(f"분봉={len(minute_data)}건")
                    summary_parts.append(f"종가={last_candle.get('close', 0):,}")
                
                if price_data:
                    summary_parts.append(f"현재가={price_data.get('current_price', 0):,}")
                    summary_parts.append(f"등락률={price_data.get('change_rate', 0):+.2f}%")
                
                if signal_data:
                    summary_parts.append(f"신호={signal_data.get('buy_signal', False)}")
                    if signal_data.get('buy_signal', False):
                        summary_parts.append(f"신뢰도={signal_data.get('confidence', 0):.1f}%")
                
                line = f"{timestamp} | 종목={stock_code} | {' | '.join(summary_parts)}\n"
                
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(line)
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 통합 데이터 로깅 오류: {e}")
    
    def create_daily_summary(self) -> str:
        """
        당일 수집 데이터 요약 리포트 생성
        
        Returns:
            str: 요약 리포트 파일 경로
        """
        try:
            summary_file = self.today_dir / f"{now_kst().strftime('%Y%m%d')}_summary.txt"
            
            # 디렉토리 내 모든 데이터 파일 분석
            minute_files = list(self.today_dir.glob("*_minute.txt"))
            price_files = list(self.today_dir.glob("*_price.txt"))
            signal_files = list(self.today_dir.glob("*_signals.txt"))
            
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(f"=== 실시간 데이터 수집 요약 ({now_kst().strftime('%Y-%m-%d')}) ===\n\n")
                
                f.write(f"📊 수집 현황:\n")
                f.write(f"  - 분봉 데이터 파일: {len(minute_files)}개\n")
                f.write(f"  - 현재가 데이터 파일: {len(price_files)}개\n")
                f.write(f"  - 매매신호 파일: {len(signal_files)}개\n\n")
                
                # 종목별 데이터 요약
                stock_codes = set()
                for file_path in (minute_files + price_files + signal_files):
                    parts = file_path.stem.split('_')
                    if len(parts) >= 3:
                        stock_codes.add(parts[1])  # 종목코드
                
                f.write(f"📈 모니터링 종목: {len(stock_codes)}개\n")
                for stock_code in sorted(stock_codes):
                    f.write(f"  - {stock_code}\n")
                
                f.write(f"\n⏰ 리포트 생성 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            self.logger.info(f"📋 일일 요약 리포트 생성: {summary_file}")
            return str(summary_file)
            
        except Exception as e:
            self.logger.error(f"❌ 일일 요약 리포트 생성 오류: {e}")
            return ""
    
    def get_file_stats(self) -> Dict[str, Any]:
        """
        현재 데이터 파일 통계 조회
        
        Returns:
            Dict: 파일 통계 정보
        """
        try:
            stats = {
                'base_dir': str(self.base_dir),
                'today_dir': str(self.today_dir),
                'total_files': 0,
                'file_types': {},
                'total_size': 0,
                'last_modified': None
            }
            
            if not self.today_dir.exists():
                return stats
            
            for file_path in self.today_dir.iterdir():
                if file_path.is_file() and file_path.suffix == '.txt':
                    stats['total_files'] += 1
                    stats['total_size'] += file_path.stat().st_size
                    
                    # 파일 타입별 분류
                    if '_minute.txt' in file_path.name:
                        stats['file_types']['minute'] = stats['file_types'].get('minute', 0) + 1
                    elif '_price.txt' in file_path.name:
                        stats['file_types']['price'] = stats['file_types'].get('price', 0) + 1
                    elif '_signals.txt' in file_path.name:
                        stats['file_types']['signals'] = stats['file_types'].get('signals', 0) + 1
                    elif '_combined.txt' in file_path.name:
                        stats['file_types']['combined'] = stats['file_types'].get('combined', 0) + 1
                    
                    # 최근 수정 시간
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if stats['last_modified'] is None or mtime > stats['last_modified']:
                        stats['last_modified'] = mtime
            
            return stats
            
        except Exception as e:
            self.logger.error(f"❌ 파일 통계 조회 오류: {e}")
            return {}
    
    def cleanup_old_files(self, keep_days: int = 7):
        """
        오래된 데이터 파일 정리
        
        Args:
            keep_days: 보관할 일수
        """
        try:
            current_date = now_kst().date()
            
            for date_dir in self.base_dir.iterdir():
                if date_dir.is_dir() and len(date_dir.name) == 8:  # YYYYMMDD 형식
                    try:
                        dir_date = datetime.strptime(date_dir.name, '%Y%m%d').date()
                        days_old = (current_date - dir_date).days
                        
                        if days_old > keep_days:
                            import shutil
                            shutil.rmtree(date_dir)
                            self.logger.info(f"🗑️ 오래된 데이터 폴더 삭제: {date_dir}")
                    except ValueError:
                        continue
                        
        except Exception as e:
            self.logger.error(f"❌ 오래된 파일 정리 오류: {e}")
    
    def __del__(self):
        """소멸자 - 파일 핸들 정리"""
        try:
            with self._lock:
                for handle in self._file_handles.values():
                    if handle and not handle.closed:
                        handle.close()
        except Exception:
            pass


# 전역 로거 인스턴스 (싱글톤 패턴)
_global_logger = None


def get_realtime_logger() -> RealtimeDataLogger:
    """전역 실시간 데이터 로거 인스턴스 반환"""
    global _global_logger
    if _global_logger is None:
        _global_logger = RealtimeDataLogger()
    return _global_logger


def log_intraday_data(stock_code: str, stock_name: str, 
                      minute_data: Optional[pd.DataFrame] = None,
                      price_data: Optional[Dict[str, Any]] = None,
                      signal_data: Optional[Dict[str, Any]] = None):
    """
    장중 데이터 로깅 편의 함수
    
    main.py의 _update_intraday_data에서 호출하기 위한 간단한 인터페이스
    
    Args:
        stock_code: 종목코드
        stock_name: 종목명
        minute_data: 분봉 데이터
        price_data: 현재가 데이터  
        signal_data: 신호 데이터
    """
    try:
        if not is_market_open():
            return  # 장시간이 아니면 로깅하지 않음
        
        logger = get_realtime_logger()
        logger.log_combined_data(stock_code, stock_name, minute_data, price_data, signal_data)
        
    except Exception as e:
        # 로깅 오류가 메인 로직에 영향을 주지 않도록
        pass