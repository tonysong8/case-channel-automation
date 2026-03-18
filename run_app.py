#!/usr/bin/env python3
"""
Case Channel Automator - 메인 실행 스크립트
"""

import os
import sys
from slack_app import flask_app, app, logger

def main():
    """메인 실행 함수"""
    try:
        # 환경 변수 검증
        required_env_vars = [
            "SLACK_BOT_TOKEN",
            "SLACK_SIGNING_SECRET"
        ]
        
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please check your .env file and ensure all required variables are set.")
            sys.exit(1)
        
        # Socket Mode 확인
        if os.getenv("SLACK_APP_TOKEN"):
            logger.info("Starting in Socket Mode...")
            # Socket Mode로 실행
            app.start(port=int(os.getenv("PORT", 3000)))
        else:
            logger.info("Starting in HTTP Mode...")
            # HTTP 모드로 실행 (웹 서버)
            port = int(os.getenv("PORT", 3000))
            debug = os.getenv("DEBUG", "false").lower() == "true"
            
            logger.info(f"Flask app starting on port {port}")
            flask_app.run(
                host="0.0.0.0",
                port=port,
                debug=debug
            )
            
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Failed to start application: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()