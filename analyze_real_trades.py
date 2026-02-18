# 실거래 내역 분석
real_trades = [
    {"time": "09:54:26", "code": "250060", "name": "모비스", "price": 3840, "action": "매수"},
    {"time": "10:09:25", "code": "007810", "name": "코리아써키트", "price": 46850, "action": "매수"},
    {"time": "10:12:25", "code": "397030", "name": "에이프릴바이오", "price": 56000, "action": "매수취소"},
    {"time": "10:27:26", "code": "397030", "name": "에이프릴바이오", "price": 56100, "action": "매수"},
    {"time": "10:54:26", "code": "071670", "name": "에이테크솔루션", "price": 10850, "action": "매수"},
    {"time": "11:06:26", "code": "080220", "name": "제주반도체", "price": 26300, "action": "매수"},
    {"time": "11:09:27", "code": "054450", "name": "텔레칩스", "price": 15500, "action": "매수"},
    {"time": "11:24:25", "code": "043260", "name": "성호전자", "price": 10150, "action": "매수취소"},
    {"time": "11:30:28", "code": "043260", "name": "성호전자", "price": 10300, "action": "매수취소"},
    {"time": "11:57:27", "code": "043260", "name": "성호전자", "price": 10350, "action": "매수"},
    {"time": "11:48:27", "code": "067290", "name": "JW신약", "price": 2265, "action": "매수취소"},
]

print("=" * 80)
print("실거래 매수 성공 종목:")
print("=" * 80)
for trade in real_trades:
    if trade["action"] == "매수":
        print(f"{trade['time']} | {trade['code']} {trade['name']:20s} | @{trade['price']:,}원")

print("\n" + "=" * 80)
print("실거래 매수 취소 종목:")
print("=" * 80)
for trade in real_trades:
    if "취소" in trade["action"]:
        print(f"{trade['time']} | {trade['code']} {trade['name']:20s} | @{trade['price']:,}원")
