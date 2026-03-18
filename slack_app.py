"""
Case Channel Automator - Slack App

Priority에 따라 채널을 생성하고 외부 사용자를 자동 초대하는 Slack App
"""

import os
import logging
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
from flask import Flask, request

# 환경 변수 로드
load_dotenv()

# Slack App 초기화
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    process_before_response=True
)

# Flask 앱 초기화
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 설정값
CONFIG = {
    "external_user_email": os.getenv("EXTERNAL_USER_EMAIL", "zealias@gmail.com"),
    "high_priority_email": os.getenv("HIGH_PRIORITY_EMAIL", "tony.song@outlook.com"),
    "medium_priority_email": os.getenv("MEDIUM_PRIORITY_EMAIL", "demoeng+jennifer_hynes_11880@slack-corp.com"),
}


class CaseChannelAutomator:
    """케이스 채널 자동화 클래스"""
    
    def __init__(self, slack_app: App):
        self.app = slack_app
        self.client = slack_app.client
        
    def normalize_channel_name(self, case_name: str) -> str:
        """채널명 정규화"""
        # 소문자 변환, 공백과 특수문자를 하이픈으로 변경
        normalized = re.sub(r'[^\w\s-]', '', case_name.lower())
        normalized = re.sub(r'[\s_]+', '-', normalized)
        normalized = re.sub(r'-+', '-', normalized)  # 연속된 하이픈 제거
        normalized = normalized.strip('-')  # 양 끝 하이픈 제거
        
        # Slack 채널명 길이 제한 (21자)
        if len(normalized) > 21:
            normalized = normalized[:21].rstrip('-')
            
        return normalized
    
    def check_if_external_user(self, email: str) -> bool:
        """외부 사용자인지 확인"""
        try:
            self.client.users_lookupByEmail(email=email)
            return False  # 내부 사용자
        except SlackApiError as e:
            if e.response["error"] == "users_not_found":
                return True  # 외부 사용자
            logger.error(f"Error checking user {email}: {e.response['error']}")
            return True  # 오류 시 외부로 간주
    
    def create_channel(self, case_name: str, case_priority: str) -> Optional[Dict[str, Any]]:
        """케이스 채널 생성"""
        try:
            channel_name = self.normalize_channel_name(case_name)
            
            # 채널 토픽과 목적 설정
            topic = f"Case: {case_name} | Priority: {case_priority.upper()}"
            purpose = f"Collaboration channel for {case_name} ({case_priority} priority case)"
            
            logger.info(f"Creating channel: {channel_name}")
            
            response = self.client.conversations_create(
                name=channel_name,
                is_private=False
            )
            
            channel_id = response["channel"]["id"]
            
            # 채널 토픽과 목적 설정
            try:
                self.client.conversations_setTopic(channel=channel_id, topic=topic)
                self.client.conversations_setPurpose(channel=channel_id, purpose=purpose)
            except SlackApiError as e:
                logger.warning(f"Failed to set channel topic/purpose: {e.response['error']}")
            
            logger.info(f"Channel created: {channel_name} (ID: {channel_id})")
            
            return {
                "id": channel_id,
                "name": channel_name,
                "topic": topic,
                "purpose": purpose
            }
            
        except SlackApiError as e:
            if e.response["error"] == "name_taken":
                # 기존 채널 찾기
                try:
                    response = self.client.conversations_list(types="public_channel")
                    for channel in response["channels"]:
                        if channel["name"] == channel_name:
                            logger.info(f"Using existing channel: {channel_name}")
                            return {
                                "id": channel["id"],
                                "name": channel_name,
                                "topic": channel.get("topic", {}).get("value", ""),
                                "purpose": channel.get("purpose", {}).get("value", "")
                            }
                except SlackApiError:
                    pass
                    
            logger.error(f"Failed to create channel {channel_name}: {e.response['error']}")
            return None
    
    def invite_internal_user(self, channel_id: str, email: str) -> bool:
        """내부 사용자 초대"""
        try:
            # 사용자 ID 찾기
            user_response = self.client.users_lookupByEmail(email=email)
            user_id = user_response["user"]["id"]
            
            # 채널에 초대
            self.client.conversations_invite(channel=channel_id, users=user_id)
            logger.info(f"Internal user {email} invited to channel {channel_id}")
            return True
            
        except SlackApiError as e:
            if e.response["error"] == "already_in_channel":
                logger.info(f"User {email} already in channel")
                return True
            else:
                logger.error(f"Failed to invite internal user {email}: {e.response['error']}")
                return False
    
    def invite_external_user(self, channel_id: str, email: str) -> bool:
        """외부 사용자 Slack Connect 초대"""
        try:
            # discoverable contact 확인
            try:
                contact_response = self.client.users_discoverableContacts_lookup(email=email)
                if contact_response.get("ok") and contact_response.get("user"):
                    user_id = contact_response["user"]["id"]
                    response = self.client.conversations_inviteShared(
                        channel=channel_id,
                        user_ids=[user_id]
                    )
                else:
                    # 이메일로 초대
                    response = self.client.conversations_inviteShared(
                        channel=channel_id,
                        emails=[email]
                    )
                    
                if response.get("ok"):
                    logger.info(f"Slack Connect invite sent to {email}")
                    return True
                else:
                    logger.error(f"Failed to send Slack Connect invite to {email}")
                    return False
                    
            except SlackApiError as e:
                logger.error(f"Failed to send Slack Connect invite to {email}: {e.response['error']}")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error inviting external user {email}: {str(e)}")
            return False
    
    def execute_case_automation(self, case_name: str, priority: str, requester_id: str) -> Dict[str, Any]:
        """케이스 자동화 실행"""
        logger.info(f"Executing case automation: {case_name}, priority: {priority}")
        
        result = {
            "success": False,
            "case_name": case_name,
            "priority": priority,
            "channel": None,
            "invitations": {
                "internal": [],
                "external": []
            },
            "errors": []
        }
        
        # 1. 채널 생성
        channel_info = self.create_channel(case_name, priority)
        if not channel_info:
            result["errors"].append("Failed to create channel")
            return result
        
        result["channel"] = channel_info
        channel_id = channel_info["id"]
        
        # 2. Priority에 따른 사용자 초대
        priority_email = (
            CONFIG["high_priority_email"] if priority.lower() == "high" 
            else CONFIG["medium_priority_email"]
        )
        
        # 2.1 Priority 사용자 초대
        is_external = self.check_if_external_user(priority_email)
        if is_external:
            success = self.invite_external_user(channel_id, priority_email)
            result["invitations"]["external"].append({
                "email": priority_email,
                "role": f"{priority.upper()} Priority User",
                "success": success
            })
        else:
            success = self.invite_internal_user(channel_id, priority_email)
            result["invitations"]["internal"].append({
                "email": priority_email,
                "role": f"{priority.upper()} Priority User", 
                "success": success
            })
        
        if not success:
            result["errors"].append(f"Failed to invite priority user: {priority_email}")
        
        # 2.2 외부 사용자 초대
        external_email = CONFIG["external_user_email"]
        external_success = self.invite_external_user(channel_id, external_email)
        result["invitations"]["external"].append({
            "email": external_email,
            "role": "External Staff",
            "success": external_success
        })
        
        if not external_success:
            result["errors"].append(f"Failed to invite external user: {external_email}")
        
        # 3. 요청자를 채널에 초대 (아직 채널에 없는 경우)
        try:
            self.client.conversations_invite(channel=channel_id, users=requester_id)
        except SlackApiError as e:
            if e.response["error"] != "already_in_channel":
                logger.warning(f"Could not invite requester to channel: {e.response['error']}")
        
        result["success"] = len(result["errors"]) == 0
        logger.info(f"Case automation completed. Success: {result['success']}")
        
        return result


# 글로벌 자동화 인스턴스
automator = CaseChannelAutomator(app)


# ============================
# 이벤트 리스너
# ============================

@app.event("app_home_opened")
def handle_app_home_opened(event, client):
    """App Home 탭이 열릴 때"""
    try:
        user_id = event["user"]
        
        # App Home 뷰 구성
        blocks = [
            {
                "type": "header", 
                "text": {
                    "type": "plain_text",
                    "text": "🤖 Case Channel Automator"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*자동으로 케이스 채널을 생성하고 적절한 사용자들을 초대합니다.*\n\n• High Priority 케이스 → `tony.song@outlook.com` 초대\n• Medium Priority 케이스 → `demoeng+jennifer_hynes_11880@slack-corp.com` 초대\n• 모든 케이스 → `zealias@gmail.com` 외부 사용자 초대 (Slack Connect)"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*사용법:*\n`/case-invite case-name priority`\n\n*예시:*\n• `/case-invite urgent-bug-fix high`\n• `/case-invite feature-request medium`"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🚨 High Priority 케이스 생성"
                        },
                        "style": "danger",
                        "action_id": "create_high_priority_case",
                        "value": "high"
                    },
                    {
                        "type": "button", 
                        "text": {
                            "type": "plain_text",
                            "text": "📋 Medium Priority 케이스 생성"
                        },
                        "style": "primary",
                        "action_id": "create_medium_priority_case",
                        "value": "medium"
                    }
                ]
            }
        ]
        
        client.views_publish(
            user_id=user_id,
            view={
                "type": "home",
                "blocks": blocks
            }
        )
        
    except Exception as e:
        logger.error(f"Error handling app home opened: {str(e)}")


@app.event("channel_created")
def handle_channel_created(event, client, logger):
    """새 채널이 생성될 때 자동 감지"""
    try:
        channel_id = event["channel"]["id"]
        channel_name = event["channel"]["name"]
        creator_id = event["channel"]["creator"]
        
        logger.info(f"Channel created: {channel_name} by {creator_id}")
        
        # 채널명에서 케이스 정보 추출 (선택사항)
        # 예: "case-urgent-bug-fix-high" 형태의 채널명 분석
        if channel_name.startswith("case-"):
            # 간단한 패턴 매칭으로 priority 추출
            if channel_name.endswith("-high"):
                priority = "high"
                case_name = channel_name.replace("case-", "").replace("-high", "")
            elif channel_name.endswith("-medium"):
                priority = "medium" 
                case_name = channel_name.replace("case-", "").replace("-medium", "")
            else:
                # Priority가 명시되지 않은 경우 medium으로 기본 설정
                priority = "medium"
                case_name = channel_name.replace("case-", "")
            
            # 자동화 실행
            logger.info(f"Auto-executing case automation for channel: {channel_name}")
            result = automator.execute_case_automation(case_name, priority, creator_id)
            
            # 결과를 채널에 메시지로 전송
            blocks = create_result_blocks(result)
            
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"케이스 채널 자동화 {'완료' if result['success'] else '실패'}",
                    blocks=blocks
                )
            except SlackApiError as e:
                logger.error(f"Failed to post automation result: {e.response['error']}")
        
    except Exception as e:
        logger.error(f"Error handling channel created event: {str(e)}")


# ============================
# Slash Commands
# ============================

@app.command("/case-invite")
def handle_case_invite_command(ack, respond, command):
    """케이스 초대 Slash Command"""
    ack()
    
    try:
        # 명령어 파라미터 파싱
        text = command.get("text", "").strip()
        user_id = command["user_id"]
        
        if not text:
            respond({
                "response_type": "ephemeral",
                "text": "❌ 사용법: `/case-invite case-name priority`\n예시: `/case-invite urgent-bug-fix high`"
            })
            return
        
        parts = text.split()
        if len(parts) < 2:
            respond({
                "response_type": "ephemeral", 
                "text": "❌ 케이스 이름과 우선순위를 모두 입력해주세요.\n예시: `/case-invite urgent-bug-fix high`"
            })
            return
        
        case_name = parts[0]
        priority = parts[1].lower()
        
        if priority not in ["high", "medium"]:
            respond({
                "response_type": "ephemeral",
                "text": "❌ 우선순위는 'high' 또는 'medium'만 가능합니다."
            })
            return
        
        # 즉시 응답 (처리 중 메시지)
        respond({
            "response_type": "ephemeral", 
            "text": f"🔄 케이스 '{case_name}' ({priority} priority) 처리 중..."
        })
        
        # 자동화 실행
        result = automator.execute_case_automation(case_name, priority, user_id)
        
        # 결과 블록 생성
        blocks = create_result_blocks(result)
        
        # 결과를 채널에 공개 메시지로 전송
        if result.get("channel"):
            channel_id = result["channel"]["id"]
            try:
                app.client.chat_postMessage(
                    channel=channel_id,
                    text=f"케이스 채널 자동화 {'완료' if result['success'] else '실패'}",
                    blocks=blocks
                )
            except SlackApiError as e:
                logger.error(f"Failed to post result to channel: {e.response['error']}")
        
        # 명령어 실행자에게 개인 메시지로도 전송
        try:
            app.client.chat_postEphemeral(
                channel=command["channel_id"],
                user=user_id,
                text=f"케이스 자동화 {'완료' if result['success'] else '실패'}",
                blocks=blocks
            )
        except SlackApiError as e:
            logger.error(f"Failed to send ephemeral message: {e.response['error']}")
        
    except Exception as e:
        logger.error(f"Error handling case-invite command: {str(e)}")
        respond({
            "response_type": "ephemeral",
            "text": f"❌ 오류가 발생했습니다: {str(e)}"
        })


# ============================
# Interactive Components
# ============================

@app.action("create_high_priority_case")
def handle_high_priority_case(ack, body, client):
    """High Priority 케이스 생성 버튼"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        
        # 모달 열기
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "case_creation_modal",
                "title": {
                    "type": "plain_text",
                    "text": "🚨 High Priority 케이스"
                },
                "submit": {
                    "type": "plain_text", 
                    "text": "생성"
                },
                "close": {
                    "type": "plain_text",
                    "text": "취소"
                },
                "private_metadata": "high",
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "case_name_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "case_name_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "예: urgent-security-vulnerability"
                            }
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "케이스 이름"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*High Priority 케이스 설정:*\n• Priority 사용자: `tony.song@outlook.com`\n• 외부 사용자: `zealias@gmail.com` (Slack Connect)\n• 채널은 공개로 생성됩니다"
                        }
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening high priority modal: {str(e)}")


@app.action("create_medium_priority_case")
def handle_medium_priority_case(ack, body, client):
    """Medium Priority 케이스 생성 버튼"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        
        # 모달 열기
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "case_creation_modal",
                "title": {
                    "type": "plain_text",
                    "text": "📋 Medium Priority 케이스"
                },
                "submit": {
                    "type": "plain_text",
                    "text": "생성"
                },
                "close": {
                    "type": "plain_text",
                    "text": "취소"
                },
                "private_metadata": "medium",
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "case_name_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "case_name_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "예: feature-enhancement-request"
                            }
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "케이스 이름"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Medium Priority 케이스 설정:*\n• Priority 사용자: `demoeng+jennifer_hynes_11880@slack-corp.com`\n• 외부 사용자: `zealias@gmail.com` (Slack Connect)\n• 채널은 공개로 생성됩니다"
                        }
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening medium priority modal: {str(e)}")


@app.view("case_creation_modal")
def handle_case_creation_modal_submission(ack, body, client, view):
    """케이스 생성 모달 제출"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        priority = view["private_metadata"]  # "high" 또는 "medium"
        
        # 입력값 추출
        case_name = view["state"]["values"]["case_name_block"]["case_name_input"]["value"]
        
        if not case_name or not case_name.strip():
            # 입력값 검증 실패
            ack({
                "response_action": "errors",
                "errors": {
                    "case_name_block": "케이스 이름을 입력해주세요."
                }
            })
            return
        
        case_name = case_name.strip()
        
        # 자동화 실행
        result = automator.execute_case_automation(case_name, priority, user_id)
        
        # 결과를 사용자에게 DM으로 전송
        blocks = create_result_blocks(result)
        
        try:
            client.chat_postMessage(
                channel=user_id,
                text=f"케이스 자동화 {'완료' if result['success'] else '실패'}",
                blocks=blocks
            )
        except SlackApiError as e:
            logger.error(f"Failed to send DM to user: {e.response['error']}")
        
        # 생성된 채널에도 메시지 전송
        if result.get("channel"):
            channel_id = result["channel"]["id"]
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"케이스 채널 자동화 {'완료' if result['success'] else '실패'}",
                    blocks=blocks
                )
            except SlackApiError as e:
                logger.error(f"Failed to post to channel: {e.response['error']}")
        
    except Exception as e:
        logger.error(f"Error handling modal submission: {str(e)}")


# ============================
# Flask Routes
# ============================

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


@flask_app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    return handler.handle(request)


@flask_app.route("/slack/commands/case-invite", methods=["POST"])
def slack_commands():
    return handler.handle(request)


@flask_app.route("/health", methods=["GET"])
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@flask_app.route("/", methods=["GET"])
def home():
    return {
        "app": "Case Channel Automator",
        "version": "1.0.0",
        "status": "running"
    }


def create_result_blocks(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """결과를 Slack Block Kit으로 변환"""
    blocks = []
    
    # 헤더
    status_emoji = "✅" if result["success"] else "❌"
    status_text = "성공" if result["success"] else "실패"
    
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{status_emoji} 케이스 채널 자동화 {status_text}"
        }
    })
    
    # 케이스 정보
    blocks.append({
        "type": "section",
        "fields": [
            {
                "type": "mrkdwn",
                "text": f"*케이스명:*\n{result['case_name']}"
            },
            {
                "type": "mrkdwn", 
                "text": f"*우선순위:*\n{result['priority'].upper()}"
            }
        ]
    })
    
    # 채널 정보
    if result.get("channel"):
        channel = result["channel"]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*생성된 채널:* <#{channel['id']}|{channel['name']}>"
            }
        })
    
    # 초대 결과
    invitations = result.get("invitations", {})
    
    # 내부 초대
    internal_invites = invitations.get("internal", [])
    if internal_invites:
        invite_text = "🏢 *내부 사용자 초대:*\n"
        for invite in internal_invites:
            status = "✅" if invite["success"] else "❌"
            invite_text += f"{status} {invite['email']} ({invite['role']})\n"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": invite_text.strip()
            }
        })
    
    # 외부 초대
    external_invites = invitations.get("external", [])
    if external_invites:
        invite_text = "🌐 *Slack Connect 초대:*\n"
        for invite in external_invites:
            status = "📤" if invite["success"] else "❌"
            invite_text += f"{status} {invite['email']} ({invite['role']})\n"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": invite_text.strip()
            }
        })
        
        if any(inv["success"] for inv in external_invites):
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💡 Slack Connect 초대는 상대방의 승인이 필요합니다."
                    }
                ]
            })
    
    # 오류 정보
    if result.get("errors"):
        error_text = "❌ *오류:*\n" + "\n".join(f"• {error}" for error in result["errors"])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": error_text
            }
        })
    
    return blocks