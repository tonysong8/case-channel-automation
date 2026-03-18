#!/bin/bash

# Slack App 배포 스크립트

set -e

echo "🚀 Case Channel Automator 배포 시작..."

# 환경 변수 확인
if [ ! -f ".env" ]; then
    echo "❌ .env 파일이 없습니다. .env.example을 참고하여 생성해주세요."
    exit 1
fi

# Docker가 설치되어 있는지 확인
if ! command -v docker &> /dev/null; then
    echo "❌ Docker가 설치되어 있지 않습니다."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose가 설치되어 있지 않습니다."
    exit 1
fi

# 환경 변수 로드
source .env

# 필수 환경 변수 확인
required_vars=("SLACK_BOT_TOKEN" "SLACK_SIGNING_SECRET")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "❌ 필수 환경 변수 $var 가 설정되지 않았습니다."
        exit 1
    fi
done

echo "✅ 환경 변수 확인 완료"

# 기존 컨테이너 중지 및 제거
echo "🛑 기존 컨테이너 중지 중..."
docker-compose down

# Docker 이미지 빌드
echo "🔨 Docker 이미지 빌드 중..."
docker-compose build --no-cache

# 애플리케이션 시작
echo "🎯 애플리케이션 시작 중..."
docker-compose up -d

echo "⏳ 애플리케이션이 시작될 때까지 대기 중..."
sleep 10

# 헬스체크
echo "🏥 헬스체크 수행 중..."
if curl -f http://localhost:3000/health > /dev/null 2>&1; then
    echo "✅ 애플리케이션이 정상적으로 실행 중입니다!"
    echo "📝 로그 확인: docker-compose logs -f"
    echo "🔗 헬스체크: http://localhost:3000/health"
else
    echo "❌ 애플리케이션이 정상적으로 시작되지 않았습니다."
    echo "로그를 확인해보세요: docker-compose logs"
    exit 1
fi

echo "🎉 배포 완료!"
echo ""
echo "📋 다음 단계:"
echo "1. Slack App 설정에서 Request URL을 https://your-domain.com/slack/events 로 설정"
echo "2. Interactive Components URL을 https://your-domain.com/slack/interactive 로 설정"
echo "3. Slash Command URL을 https://your-domain.com/slack/commands/case-invite 로 설정"