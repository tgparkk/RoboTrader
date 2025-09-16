import re
import os
import pandas as pd
from datetime import datetime
import numpy as np

def parse_trading_logs(file_path):
    """매매 로그 파일 파싱"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 매매 결과 패턴 매칭
    pattern = r'(\d{2}:\d{2}) 매수\[pullback_pattern\] @([\d,]+) → (\d{2}:\d{2}) 매도\[(profit_\d+\.\d+pct|stop_loss_\d+\.\d+pct)\] @([\d,]+) \(([+-]\d+\.\d+%)\)'
    matches = re.findall(pattern, content)

    results = []
    for match in matches:
        buy_time, buy_price, sell_time, sell_reason, sell_price, profit_pct = match
        buy_price = int(buy_price.replace(',', ''))
        sell_price = int(sell_price.replace(',', ''))
        profit_pct = float(profit_pct.replace('%', ''))

        results.append({
            'buy_time': buy_time,
            'buy_price': buy_price,
            'sell_time': sell_time,
            'sell_reason': sell_reason,
            'sell_price': sell_price,
            'profit_pct': profit_pct,
            'win': profit_pct > 0
        })

    return results

def parse_signal_details(file_path):
    """신호 상세 정보 파싱"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 신호 상세 패턴 매칭
    pattern = r'(\d{2}:\d{2})→(\d{2}:\d{2}): 종가:([\d,]+) \| 거래량:([\d,]+) \| 🟢강매수 \| 신뢰도:(\d+)% \| 💰매수@([\d,]+) \| →(\d{2}:\d{2})매도@([\d,]+)'
    matches = re.findall(pattern, content)

    results = []
    for match in matches:
        signal_start, signal_end, close_price, volume, confidence, buy_price, sell_time, sell_price = match

        results.append({
            'signal_start': signal_start,
            'signal_end': signal_end,
            'close_price': int(close_price.replace(',', '')),
            'volume': int(volume.replace(',', '')),
            'confidence': int(confidence),
            'buy_price': int(buy_price.replace(',', '')),
            'sell_time': sell_time,
            'sell_price': int(sell_price.replace(',', ''))
        })

    return results

def main():
    # 09/08-09/16 로그 파일 처리
    log_dir = 'signal_replay_log'
    target_files = []

    for day in range(8, 17):  # 09/08 ~ 09/16
        if day == 6 or day == 7 or day == 13 or day == 14:  # 주말 제외
            continue
        day_str = f'{day:02d}'
        filename = f'signal_new2_replay_202509{day_str}_9_00_0.txt'
        if os.path.exists(os.path.join(log_dir, filename)):
            target_files.append(filename)

    all_trades = []
    daily_stats = {}

    print("=== 파일 처리 중 ===")
    for file in sorted(target_files):
        date = file.split('_')[2][:8]
        print(f"처리 중: {file}")

        try:
            trades = parse_trading_logs(os.path.join(log_dir, file))
            signal_details = parse_signal_details(os.path.join(log_dir, file))

            # 매매와 신호 상세를 매칭
            for trade in trades:
                for signal in signal_details:
                    if trade['buy_price'] == signal['buy_price'] and trade['sell_price'] == signal['sell_price']:
                        trade.update({
                            'close_price': signal['close_price'],
                            'volume': signal['volume'],
                            'confidence': signal['confidence']
                        })
                        break

            wins = sum(1 for t in trades if t['win'])
            losses = len(trades) - wins
            win_rate = wins / len(trades) * 100 if trades else 0

            daily_stats[date] = {
                'trades': len(trades),
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate
            }

            all_trades.extend([(date, t) for t in trades])

        except Exception as e:
            print(f"오류 발생 ({file}): {e}")

    # 전체 통계
    total_trades = len(all_trades)
    total_wins = sum(1 for _, t in all_trades if t['win'])
    total_losses = total_trades - total_wins
    overall_win_rate = total_wins / total_trades * 100 if total_trades else 0

    print(f'\n=== 09/08-09/16 매매 결과 분석 ===')
    print(f'전체 거래: {total_trades}건')
    print(f'승리: {total_wins}건, 패배: {total_losses}건')
    print(f'승률: {overall_win_rate:.1f}%')
    print()

    print('=== 일별 통계 ===')
    for date, stats in daily_stats.items():
        print(f'{date}: {stats["trades"]}건 (승:{stats["wins"]}, 패:{stats["losses"]}, 승률:{stats["win_rate"]:.1f}%)')

    # 승패 분석
    wins = [(date, t) for date, t in all_trades if t['win']]
    losses = [(date, t) for date, t in all_trades if not t['win']]

    print(f'\n=== 승리 거래 분석 (총 {len(wins)}건) ===')
    if wins:
        win_confidences = [t['confidence'] for _, t in wins if 'confidence' in t]
        win_volumes = [t['volume'] for _, t in wins if 'volume' in t]
        if win_confidences:
            print(f'평균 신뢰도: {np.mean(win_confidences):.1f}%')
        if win_volumes:
            print(f'평균 거래량: {np.mean(win_volumes):,.0f}')

    print(f'\n=== 패배 거래 분석 (총 {len(losses)}건) ===')
    if losses:
        loss_confidences = [t['confidence'] for _, t in losses if 'confidence' in t]
        loss_volumes = [t['volume'] for _, t in losses if 'volume' in t]
        if loss_confidences:
            print(f'평균 신뢰도: {np.mean(loss_confidences):.1f}%')
        if loss_volumes:
            print(f'평균 거래량: {np.mean(loss_volumes):,.0f}')

        print('\n패배 거래 상세 (처음 15건):')
        for i, (date, trade) in enumerate(losses[:15]):
            conf = trade.get('confidence', 'N/A')
            vol = trade.get('volume', 'N/A')
            vol_str = f'{vol:,}' if vol != 'N/A' else 'N/A'
            print(f'{i+1:2d}. {date} {trade["buy_time"]}→{trade["sell_time"]}: @{trade["buy_price"]:,}→@{trade["sell_price"]:,} ({trade["profit_pct"]:.2f}%) [신뢰도:{conf}%, 거래량:{vol_str}]')

    # DataFrame으로 변환하여 저장
    df_data = []
    for date, trade in all_trades:
        df_data.append({
            'date': date,
            'buy_time': trade['buy_time'],
            'sell_time': trade['sell_time'],
            'buy_price': trade['buy_price'],
            'sell_price': trade['sell_price'],
            'profit_pct': trade['profit_pct'],
            'win': trade['win'],
            'confidence': trade.get('confidence', None),
            'volume': trade.get('volume', None),
            'close_price': trade.get('close_price', None)
        })

    df = pd.DataFrame(df_data)
    df.to_csv('trading_results_0908_0916.csv', index=False, encoding='utf-8-sig')
    print(f'\n결과를 trading_results_0908_0916.csv 파일로 저장했습니다.')

    return df

if __name__ == "__main__":
    df = main()