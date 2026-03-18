# Slack App 설정 가이드

## 1. Slack App 생성

1. [Slack API 웹사이트](https://api.slack.com/apps) 방문
2. "Create New App" 클릭
3. "From an app manifest" 선택
4. 워크스페이스 선택
5. `app_manifest.json` 파일의 내용을 붙여넣기
6. "Create" 클릭

## 2. 기본 정보 설정

### App Credentials 복사
**Basic Information** 페이지에서:
- **Signing Secret** → `.env` 파일의 `SLACK_SIGNING_SECRET`
- **App-Level Tokens** (Socket Mode 사용시) → `SLACK_APP_TOKEN`

### Bot Token 복사  
**OAuth & Permissions** 페이지에서:
- **Bot User OAuth Token** (xoxb-로 시작) → `SLACK_BOT_TOKEN`

## 3. 배포 URL 설정

앱을 배포한 후 다음 URL들을 설정하세요:

### Event Subscriptions
- **Enable Events**: ON
- **Request URL**: `https://your-domain.com/slack/events`

### Interactivity & Shortcuts  
- **Interactivity**: ON
- **Request URL**: `https://your-domain.com/slack/interactive`

### Slash Commands
`/case-invite` 명령어:
- **Command**: `/case-invite`
- **Request URL**: `https://your-domain.com/slack/commands/case-invite`
- **Short Description**: "케이스 채널을 생성하고 사용자들을 초대합니다"
- **Usage Hint**: `case-name priority(high/medium)`

## 4. 권한 설정 확인

**OAuth & Permissions**에서 다음 Bot Token Scopes가 있는지 확인:

### 필수 스코프
- `channels:write` - 채널 생성
- `channels:manage` - 채널 관리  
- `channels:read` - 채널 정보 읽기
- `chat:write` - 메시지 전송
- `users:read` - 사용자 정보 읽기
- `users:read.email` - 사용자 이메일 읽기
- `commands` - Slash Command 사용
- `app_mentions:read` - 앱 멘션 읽기

### Slack Connect 스코프
- `conversations.connect:write` - 외부 초대 전송
- `conversations.connect:read` - 초대 이벤트 읽기

## 5. 이벤트 구독 설정

**Event Subscriptions**에서 다음 Bot Events 구독:
- `channel_created` - 새 채널 생성 시 자동 처리
- `member_joined_channel` - 채널 참가 이벤트
- `app_home_opened` - App Home 탭 열기

## 6. App Home 설정

**App Home**에서:
- **Home Tab**: ON
- **Messages Tab**: OFF (선택사항)

## 7. 워크스페이스에 앱 설치

1. **OAuth & Permissions** → "Install to Workspace" 클릭
2. 권한 승인
3. Bot Token이 생성되었는지 확인

## 8. Socket Mode 설정 (옵션)

개발 환경에서 공개 URL 없이 테스트하려면:

1. **Socket Mode** → "Enable Socket Mode" ON
2. **App-Level Token** 생성:
   - Token Name: `socket_token`
   - Scopes: `connections:write`
3. 생성된 토큰을 `SLACK_APP_TOKEN`에 설정

## 9. 환경 변수 설정

`.env` 파일 생성:
```bash
# 필수 설정
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret

# Socket Mode 사용시 (개발환경)
SLACK_APP_TOKEN=xapp-your-app-token

# 선택 설정
EXTERNAL_USER_EMAIL=zealias@gmail.com
HIGH_PRIORITY_EMAIL=tony.song@outlook.com  
MEDIUM_PRIORITY_EMAIL=demoeng+jennifer_hynes_11880@slack-corp.com
```

## 10. 앱 배포 및 테스트

### 로컬 테스트 (Socket Mode)
```bash
./dev.sh
```

### 프로덕션 배포
```bash
./deploy.sh
```

### 기능 테스트
1. `/case-invite test-case high` 명령어 실행
2. App Home 탭에서 버튼 클릭
3. `case-` 접두사로 채널 생성하여 자동 감지 테스트

## 11. 문제 해결

### URL 검증 실패
- HTTPS 사용 필수
- 공개 접근 가능한 URL
- 올바른 경로 설정

### 권한 오류
- 필요한 모든 스코프 추가 확인
- 앱 재설치 필요할 수 있음

### 이벤트 수신 안됨
- Request URL 응답 속도 3초 이내
- 200 상태 코드 반환 확인

## 12. 프로덕션 고려사항

### 보안
- 환경 변수로 토큰 관리
- HTTPS 필수
- Request 검증 활성화

### 모니터링
- 로그 수집 설정
- 헬스체크 엔드포인트 활용
- 오류 추적 시스템 구성

### 확장성
- 로드 밸런서 구성
- 데이터베이스 연동 (케이스 추적용)
- 캐싱 레이어 추가