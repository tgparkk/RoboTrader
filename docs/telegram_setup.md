# 텔레그램 모니터링 설정 가이드

RoboTrader 시스템에 텔레그램 모니터링 기능을 설정하는 방법을 안내합니다.

## 1. 텔레그램 봇 생성

### 1.1 BotFather와 대화 시작
1. 텔레그램에서 `@BotFather` 검색
2. `/start` 명령어 입력
3. `/newbot` 명령어로 새 봇 생성

### 1.2 봇 정보 설정
```
BotFather: What do you want to name your bot?
You: RoboTrader Bot

BotFather: What do you want your bot's username to be?
You: YourRoboTraderBot
```

### 1.3 봇 토큰 확인
- BotFather가 제공하는 토큰을 복사하세요
- 형식: `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`

## 2. Chat ID 확인

### 2.1 봇과 대화 시작
1. 생성한 봇을 검색해서 대화 시작
2. `/start` 메시지 전송

### 2.2 Chat ID 조회
브라우저에서 다음 URL 접속:
```
https://api.telegram.org/bot{YOUR_BOT_TOKEN}/getUpdates
```

응답에서 `chat.id` 값을 확인:
```json
{
  "ok": true,
  "result": [
    {
      "update_id": 123456789,
      "message": {
        "message_id": 1,
        "from": {...},
        "chat": {
          "id": 987654321,  ← 이 값이 Chat ID
          "type": "private"
        },
        "text": "/start"
      }
    }
  ]
}
```

## 3. 설정 파일 수정

`config/key.ini` 파일에 텔레그램 섹션을 추가:

```ini
[KIS]
# 한국투자증권 API 설정
KIS_BASE_URL="https://openapi.koreainvestment.com:9443"
KIS_APP_KEY="YOUR_APP_KEY"
KIS_APP_SECRET="YOUR_APP_SECRET"
KIS_ACCOUNT_NO="YOUR_ACCOUNT_NO"
KIS_HTS_ID="YOUR_HTS_ID"

[TELEGRAM]
enabled=true
token=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
chat_id=987654321
```

### 설정 값 설명:
- `enabled`: 텔레그램 기능 활성화 여부 (true/false)
- `token`: BotFather에서 받은 봇 토큰
- `chat_id`: 메시지를 받을 채팅 ID

## 4. 사용 가능한 명령어

봇과 대화에서 사용할 수 있는 명령어들:

### 📊 `/status`
현재 시스템 상태를 조회합니다.
```
📊 시스템 상태

⏰ 시간: 14:30:25
📈 시장: 장중
🔄 상태: 정상 동작
📊 데이터: 수집 중
```

### 💼 `/positions`
현재 보유 포지션을 조회합니다.
```
💼 보유 포지션

삼성전자(005930): 100주
- 평균단가: 70,000원
- 현재가: 71,500원
- 평가손익: +150,000원 (+2.14%)
```

### 📋 `/orders`
주문 현황을 조회합니다.
```
📋 주문 현황

미체결 주문: 2건
완료된 주문: 5건

[미체결]
- SK하이닉스 매수 50주 @130,000원
- NAVER 매도 30주 @320,000원
```

### 🆘 `/help`
사용 가능한 명령어 목록을 표시합니다.

## 5. 자동 알림 종류

### 🚀 시스템 시작/종료
```
🚀 거래 시스템 시작
시간: 08:45:00
상태: 초기화 완료
```

### 📝 주문 실행
```
📝 주문 실행
종목: 삼성전자(005930)
구분: 매수
수량: 100주
가격: 70,000원
주문ID: 20240127001
```

### ✅ 주문 체결
```
✅ 주문 체결
종목: 삼성전자(005930)
구분: 매수
수량: 100주
가격: 70,000원
손익: +0원
```

### 🔥 매매 신호
```
🔥 매매 신호
종목: NAVER(035420)
신호: 매수
가격: 180,000원
근거: 2.5% 급등 감지
```

### ⚠️ 시스템 오류
```
⚠️ 시스템 오류
시간: 14:25:30
모듈: OrderManager
오류: 네트워크 연결 실패
```

### 📈 일일 거래 요약
```
📈 일일 거래 요약
날짜: 2024-01-27
총 거래: 8회
수익률: +1.25%
손익: +125,000원
```

## 6. 보안 주의사항

### ⚠️ 중요 보안 규칙
1. **봇 토큰을 절대 공유하지 마세요**
2. **Chat ID를 다른 사람에게 알리지 마세요**
3. **설정 파일을 Git에 커밋하지 마세요**
4. **봇을 공개 그룹에 추가하지 마세요**

### 🔒 보안 설정
- 봇은 오직 설정된 Chat ID에서만 명령을 받습니다
- 다른 사용자의 명령은 무시됩니다
- 민감한 계좌 정보는 마스킹 처리됩니다

## 7. 문제 해결

### 메시지가 오지 않는 경우
1. `enabled: true`로 설정되었는지 확인
2. 봇 토큰이 올바른지 확인
3. Chat ID가 정확한지 확인
4. 봇과 대화를 시작했는지 확인

### 명령어가 작동하지 않는 경우
1. 봇이 정상적으로 시작되었는지 로그 확인
2. Chat ID가 일치하는지 확인
3. 시스템이 정상 동작 중인지 확인

### 로그 확인
```bash
tail -f logs/trading_YYYYMMDD.log | grep -i telegram
```

## 8. 고급 설정

### 알림 세부 설정
텔레그램 알림 설정은 `core/telegram_integration.py` 파일의 `notification_settings`에서 조정할 수 있습니다:

```python
self.notification_settings = {
    'system_events': True,      # 시스템 시작/종료
    'order_events': True,       # 주문 관련
    'signal_events': True,      # 매매 신호
    'error_events': True,       # 오류 발생
    'daily_summary': True,      # 일일 요약
    'periodic_status': True,    # 주기적 상태 알림
    'interval_minutes': 30      # 30분마다 상태 알림
}
```

### 알림 비활성화
특정 알림을 끄고 싶다면 해당 값을 `False`로 변경:
```python
'signal_events': False,  # 매매 신호 알림 끄기
'periodic_status': False, # 주기적 상태 알림 끄기
```

이제 텔레그램을 통해 RoboTrader를 편리하게 모니터링할 수 있습니다!