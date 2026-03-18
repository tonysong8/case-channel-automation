# Case Channel Automator - Slack App

Priority에 따라 케이스 채널을 자동 생성하고 외부 사용자를 **Slack Connect**를 통해 초대하는 완전한 Slack App입니다.

## 🎯 주요 기능

### 🤖 자동화 기능
- **케이스 채널 자동 생성**: 정규화된 채널명으로 생성
- **Priority 기반 사용자 초대**:
  - High Priority: `tony.song@outlook.com`
  - Medium Priority: `demoeng+jennifer_hynes_11880@slack-corp.com`
- **외부 사용자 자동 초대**: `zealias@gmail.com` (Slack Connect)

### 💻 사용자 인터페이스
- **App Home**: 버튼 클릭으로 쉬운 케이스 생성
- **Slash Command**: `/case-invite case-name priority`
- **Interactive Modals**: 사용자 친화적인 폼
- **Rich Notifications**: Block Kit을 활용한 상세한 결과 표시

### 🔄 이벤트 기반
- **실시간 채널 감지**: `case-` 접두사 채널 자동 처리
- **자동 결과 알림**: 채널과 DM으로 결과 전송

## 🚀 빠른 시작

### 1. 환경 설정
```bash
# 저장소 클론
git clone <your-repo>
cd case-sc-automation

# 환경 파일 생성
cp .env.app.example .env
# .env 파일을 편집하여 Slack 토큰 설정
```

### 2. 개발 모드 실행
```bash
./dev.sh
```

### 3. 프로덕션 배포
```bash
./deploy.sh
```

## 🔧 Slack App 설정

### 1. Slack App 생성
1. [Slack API 사이트](https://api.slack.com/apps)에서 "Create New App" 선택
2. "From an app manifest" 선택
3. `app_manifest.json` 내용 붙여넣기

### 2. 토큰 및 시크릿 가져오기
- **Bot User OAuth Token**: `xoxb-...` (SLACK_BOT_TOKEN)
- **Signing Secret**: App 설정의 Basic Information에서 복사
- **App-Level Token**: Socket Mode 사용시 필요 (SLACK_APP_TOKEN)

### 3. 필수 OAuth 스코프
```
channels:write, channels:manage, channels:read
chat:write, users:read, users:read.email
conversations.connect:write, conversations.connect:read
app_mentions:read, commands
```

### 4. 이벤트 구독 설정
- **Request URL**: `https://your-domain.com/slack/events`
- **Bot Events**: `channel_created`, `member_joined_channel`, `app_home_opened`

### 5. Interactive Components
- **Request URL**: `https://your-domain.com/slack/interactive`

### 6. Slash Commands
- **Command**: `/case-invite`
- **Request URL**: `https://your-domain.com/slack/commands/case-invite`
- **Description**: "케이스 채널을 생성하고 사용자들을 초대합니다"

## 📊 사용법

### Slash Command
```bash
/case-invite urgent-security-fix high
/case-invite feature-enhancement medium
```

### App Home
1. Slack에서 "Case Channel Automator" 앱 클릭
2. "Home" 탭에서 버튼 클릭
3. 모달에서 케이스 이름 입력

### 자동 감지
`case-` 접두사로 시작하는 채널 생성시 자동으로 처리:
```
case-urgent-bug-fix-high    → High Priority로 처리
case-feature-request-medium → Medium Priority로 처리
case-general-issue         → Medium Priority로 기본 처리
```

## 🐳 배포 옵션

### Docker (권장)
```bash
# 개발용
docker-compose up -d

# 프로덕션용 (nginx 포함)
docker-compose --profile production up -d
```

### 로컬 개발
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_app.txt
python run_app.py
```

### 클라우드 배포
- **Heroku**: Procfile 포함
- **AWS/GCP/Azure**: Docker 이미지 사용
- **ngrok**: 로컬 개발시 터널링

## 📋 환경 변수

| 변수명 | 필수 | 설명 |
|--------|------|------|
| `SLACK_BOT_TOKEN` | ✅ | Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | ✅ | 앱 시그니처 검증용 |
| `SLACK_APP_TOKEN` | ⚠️ | Socket Mode용 (옵션) |
| `EXTERNAL_USER_EMAIL` | ❌ | 외부 사용자 이메일 |
| `HIGH_PRIORITY_EMAIL` | ❌ | High Priority 사용자 |
| `MEDIUM_PRIORITY_EMAIL` | ❌ | Medium Priority 사용자 |
| `PORT` | ❌ | 서버 포트 (기본: 3000) |
| `DEBUG` | ❌ | 디버그 모드 |
| `LOG_LEVEL` | ❌ | 로그 레벨 |

## 🔍 모니터링

### 헬스체크
```bash
curl http://localhost:3000/health
```

### 로그 확인
```bash
# Docker
docker-compose logs -f

# 로컬
tail -f logs/app.log
```

### 메트릭
- 채널 생성 성공률
- 초대 성공률 (내부/외부별)
- 응답 시간

## 🛠️ 개발

### 코드 구조
```
slack_app.py          # 메인 Slack App 로직
run_app.py           # 앱 실행 스크립트
app_manifest.json    # Slack App 매니페스트
requirements_app.txt # Python 의존성
Dockerfile          # Docker 빌드 설정
docker-compose.yml  # 컨테이너 오케스트레이션
```

### 테스트
```bash
# 유닛 테스트
pytest test_slack_app.py

# 통합 테스트
python test_integration.py
```

### 기여하기
1. Fork 저장소
2. Feature 브랜치 생성
3. 변경사항 커밋
4. Pull Request 제출

## 🚨 문제 해결

### 일반적인 오류

**"missing_scope" 오류**
```bash
# Slack App 설정에서 필요한 스코프 추가
conversations.connect:write
conversations.connect:read
```

**외부 초대 실패**
```bash
# 1. Slack Connect가 조직에서 활성화되어 있는지 확인
# 2. 대상 이메일이 유효한지 확인  
# 3. 로그에서 상세 오류 확인
```

**이벤트 수신 안됨**
```bash
# 1. Request URL이 올바른지 확인
# 2. HTTPS 사용하는지 확인
# 3. 방화벽 설정 확인
```

### 로그 분석
```bash
# 오류 로그만 필터링
docker-compose logs | grep ERROR

# 특정 기능 로그 추적
docker-compose logs | grep "case automation"
```

## 📄 라이센스

MIT License - 자유롭게 사용, 수정, 배포 가능합니다.

---

## 🆘 지원

문제가 있으시면 GitHub Issues를 통해 문의해주세요:
- 🐛 버그 리포트
- 🚀 기능 제안
- 📖 문서 개선
- ❓ 사용법 질문