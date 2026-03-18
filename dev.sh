#!/bin/bash

# 개발 서버 실행 스크립트

set -e

echo "🔧 Case Channel Automator 개발 모드 시작..."

# Python 가상환경 확인 및 생성
if [ ! -d "venv" ]; then
    echo "📦 Python 가상환경 생성 중..."
    python3 -m venv venv
fi

# 가상환경 활성화
echo "🔌 가상환경 활성화..."
source venv/bin/activate

# 의존성 설치
echo "📚 의존성 설치 중..."
pip install -r requirements.txt

# 환경 변수 확인
if [ ! -f ".env" ]; then
    echo "⚠️  .env 파일이 없습니다. .env.example을 복사하여 생성합니다."
    cp .env.example .env
    echo "📝 .env 파일을 편집하여 Slack 토큰을 설정해주세요."
    read -p "계속하려면 Enter를 누르세요..."
fi

# 환경 변수 로드
source .env

# 필수 환경 변수 확인
if [ -z "$SLACK_BOT_TOKEN" ] || [ -z "$SLACK_SIGNING_SECRET" ]; then
    echo "❌ SLACK_BOT_TOKEN과 SLACK_SIGNING_SECRET을 .env 파일에 설정해주세요."
    exit 1
fi

echo "✅ 환경 설정 완료"

# 개발 모드 설정
export DEBUG=true
export LOG_LEVEL=DEBUG

echo "🚀 개발 서버 시작..."
echo "📝 로그 레벨: DEBUG"
echo "🔗 서버 주소: http://localhost:3000"
echo "🏥 헬스체크: http://localhost:3000/health"
echo ""
echo "💡 Socket Mode를 사용하려면 SLACK_APP_TOKEN을 .env에 추가하세요."
echo ""

# 애플리케이션 시작
python run_app.py