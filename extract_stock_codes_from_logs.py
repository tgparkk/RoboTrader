import re
import os
from typing import Dict, List, Set

def extract_stock_codes_from_log_file(file_path: str) -> List[str]:
    """로그 파일에서 종목코드들을 추출"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 종목코드 패턴: "=== 065500 -" 형태
    pattern = r'=== (\d{6}) -'
    matches = re.findall(pattern, content)

    return list(set(matches))  # 중복 제거

def parse_trades_with_stock_codes():
    """매매 결과와 종목코드를 매칭"""
    log_dir = 'signal_replay_log'
    target_files = []

    for day in range(8, 17):  # 09/08 ~ 09/16
        if day in [6, 7, 13, 14]:  # 주말 제외
            continue
        day_str = f'{day:02d}'
        filename = f'signal_new2_replay_202509{day_str}_9_00_0.txt'
        if os.path.exists(os.path.join(log_dir, filename)):
            target_files.append(filename)

    all_trades = []

    for file in sorted(target_files):
        date = file.split('_')[2][:8]
        print(f"파싱 중: {file}")

        try:
            with open(os.path.join(log_dir, file), 'r', encoding='utf-8') as f:
                content = f.read()

            # 종목별로 섹션을 나눔
            sections = re.split(r'=== (\d{6}) -', content)[1:]  # 첫 번째 빈 섹션 제거

            # 섹션을 종목코드와 내용으로 분할
            for i in range(0, len(sections), 2):
                if i + 1 < len(sections):
                    stock_code = sections[i]
                    section_content = sections[i + 1]

                    # 해당 섹션에서 매매 결과 찾기
                    pattern = r'(\d{2}:\d{2}) 매수\[pullback_pattern\] @([\d,]+) → (\d{2}:\d{2}) 매도\[(profit_\d+\.\d+pct|stop_loss_\d+\.\d+pct)\] @([\d,]+) \(([+-]\d+\.\d+%)\)'
                    matches = re.findall(pattern, section_content)

                    for match in matches:
                        buy_time, buy_price, sell_time, sell_reason, sell_price, profit_pct = match
                        buy_price_int = int(buy_price.replace(',', ''))
                        sell_price_int = int(sell_price.replace(',', ''))
                        profit_pct_float = float(profit_pct.replace('%', ''))

                        trade_info = {
                            'date': date,
                            'stock_code': stock_code,
                            'buy_time': buy_time,
                            'sell_time': sell_time,
                            'buy_price': buy_price_int,
                            'sell_price': sell_price_int,
                            'profit_pct': profit_pct_float,
                            'win': profit_pct_float > 0
                        }

                        all_trades.append(trade_info)

        except Exception as e:
            print(f"파일 처리 오류 ({file}): {e}")

    return all_trades

def main():
    # 종목코드 매칭 테스트
    trades = parse_trades_with_stock_codes()

    print(f"총 {len(trades)}건의 매매 발견")

    # 종목코드별 통계
    stock_stats = {}
    for trade in trades:
        stock = trade['stock_code']
        if stock not in stock_stats:
            stock_stats[stock] = {'total': 0, 'wins': 0, 'losses': 0}

        stock_stats[stock]['total'] += 1
        if trade['win']:
            stock_stats[stock]['wins'] += 1
        else:
            stock_stats[stock]['losses'] += 1

    print(f"\n=== 종목별 승패 통계 ===")
    print(f"{'종목코드':<8} {'총거래':<6} {'승리':<4} {'패배':<4} {'승률':<6}")
    print("-" * 35)

    for stock, stats in sorted(stock_stats.items()):
        win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
        print(f"{stock:<8} {stats['total']:<6} {stats['wins']:<4} {stats['losses']:<4} {win_rate:<5.1f}%")

    # 승리/패배 종목 리스트
    winning_stocks = [stock for stock, stats in stock_stats.items() if stats['wins'] > stats['losses']]
    losing_stocks = [stock for stock, stats in stock_stats.items() if stats['wins'] <= stats['losses']]

    print(f"\n승리 우세 종목 ({len(winning_stocks)}개): {', '.join(winning_stocks)}")
    print(f"패배 우세 종목 ({len(losing_stocks)}개): {', '.join(losing_stocks[:10])}")  # 처음 10개만

    return trades

if __name__ == "__main__":
    main()