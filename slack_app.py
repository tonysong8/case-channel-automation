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
import threading

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

# 사용자별 이메일 설정을 저장하기 위한 메모리 저장소 (프로덕션에서는 데이터베이스 사용 권장)
USER_EMAIL_SETTINGS = {}
EMAIL_LOCK = threading.Lock()

# 기본 설정값
DEFAULT_CONFIG = {
    "external_user_email": os.getenv("EXTERNAL_USER_EMAIL", "zealias@gmail.com"),
    "high_priority_email": os.getenv("HIGH_PRIORITY_EMAIL", "tony.song@outlook.com"),
    "medium_priority_email": os.getenv("MEDIUM_PRIORITY_EMAIL", "demoeng+jennifer_hynes_11880@slack-corp.com"),
}


def get_user_email_config(user_id: str) -> Dict[str, str]:
    """사용자별 이메일 설정 가져오기"""
    with EMAIL_LOCK:
        return USER_EMAIL_SETTINGS.get(user_id, DEFAULT_CONFIG.copy())


def set_user_email_config(user_id: str, config: Dict[str, str]):
    """사용자별 이메일 설정 저장"""
    with EMAIL_LOCK:
        USER_EMAIL_SETTINGS[user_id] = config


def validate_email(email: str) -> bool:
    """이메일 형식 검증"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


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
    
    def execute_case_automation(self, case_name: str, priority: str, requester_id: str, custom_emails: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
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
        
        # 사용자별 이메일 설정 가져오기
        if custom_emails:
            email_config = custom_emails
        else:
            email_config = get_user_email_config(requester_id)
        
        # 1. 채널 생성
        channel_info = self.create_channel(case_name, priority)
        if not channel_info:
            result["errors"].append("Failed to create channel")
            return result
        
        result["channel"] = channel_info
        channel_id = channel_info["id"]
        
        # 2. Priority에 따른 사용자 초대
        priority_email = (
            email_config["high_priority_email"] if priority.lower() == "high" 
            else email_config["medium_priority_email"]
        )
        
        # 2.1 Priority 사용자 초대
        if priority_email and priority_email.strip():
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
        external_email = email_config["external_user_email"]
        if external_email and external_email.strip():
            external_success = self.invite_external_user(channel_id, external_email)
            result["invitations"]["external"].append({
                "email": external_email,
                "role": "External Staff",
                "success": external_success
            })
            
            if not external_success:
                result["errors"].append(f"Failed to invite external user: {external_email}")
        
        # 3. 추가 이메일들 초대 (custom_emails에 있는 경우)
        if custom_emails and custom_emails.get("additional_emails"):
            additional_emails = [email.strip() for email in custom_emails["additional_emails"].split(",") if email.strip()]
            for email in additional_emails:
                if validate_email(email):
                    is_external = self.check_if_external_user(email)
                    if is_external:
                        success = self.invite_external_user(channel_id, email)
                        result["invitations"]["external"].append({
                            "email": email,
                            "role": "Additional User",
                            "success": success
                        })
                    else:
                        success = self.invite_internal_user(channel_id, email)
                        result["invitations"]["internal"].append({
                            "email": email,
                            "role": "Additional User",
                            "success": success
                        })
                    
                    if not success:
                        result["errors"].append(f"Failed to invite additional user: {email}")
                else:
                    result["errors"].append(f"Invalid email format: {email}")
        
        # 4. 요청자를 채널에 초대 (아직 채널에 없는 경우)
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
        user_config = get_user_email_config(user_id)
        
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
                    "text": "*자동으로 케이스 채널을 생성하고 적절한 사용자들을 초대합니다.*"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*현재 이메일 설정:*"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*High Priority:*\n`{user_config.get('high_priority_email', '설정되지 않음')}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Medium Priority:*\n`{user_config.get('medium_priority_email', '설정되지 않음')}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*외부 사용자:*\n`{user_config.get('external_user_email', '설정되지 않음')}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": " "
                    }
                ]
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "⚙️ 이메일 설정"
                        },
                        "style": "primary",
                        "action_id": "configure_emails"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*케이스 생성:*"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🚨 High Priority 케이스"
                        },
                        "style": "danger",
                        "action_id": "create_high_priority_case",
                        "value": "high"
                    },
                    {
                        "type": "button", 
                        "text": {
                            "type": "plain_text",
                            "text": "📋 Medium Priority 케이스"
                        },
                        "style": "primary",
                        "action_id": "create_medium_priority_case",
                        "value": "medium"
                    }
                ]
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button", 
                        "text": {
                            "type": "plain_text",
                            "text": "🎯 커스텀 케이스 생성"
                        },
                        "action_id": "create_custom_case"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*사용법:*\n• 위 버튼을 클릭하여 케이스 생성\n• `/case-invite case-name priority` 명령어 사용\n• `case-` 접두사로 채널을 생성하면 자동 처리"
                }
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

@app.action("configure_emails")
def handle_configure_emails(ack, body, client):
    """이메일 설정 버튼"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        user_config = get_user_email_config(user_id)
        
        # 이메일 설정 모달 열기
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "email_settings_modal",
                "title": {
                    "type": "plain_text",
                    "text": "⚙️ 이메일 설정"
                },
                "submit": {
                    "type": "plain_text", 
                    "text": "저장"
                },
                "close": {
                    "type": "plain_text",
                    "text": "취소"
                },
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*케이스 생성시 초대할 사용자 이메일을 설정하세요.*"
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "high_priority_email_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "high_priority_email_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "high priority 케이스에 초대할 이메일"
                            },
                            "initial_value": user_config.get("high_priority_email", "")
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "High Priority 사용자 이메일"
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "medium_priority_email_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "medium_priority_email_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "medium priority 케이스에 초대할 이메일"
                            },
                            "initial_value": user_config.get("medium_priority_email", "")
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "Medium Priority 사용자 이메일"
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "external_user_email_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "external_user_email_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "외부 사용자 이메일 (Slack Connect)"
                            },
                            "initial_value": user_config.get("external_user_email", "")
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "외부 사용자 이메일"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "💡 외부 사용자는 Slack Connect를 통해 자동 초대됩니다. 빈 칸으로 두면 해당 사용자는 초대하지 않습니다."
                            }
                        ]
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening email settings modal: {str(e)}")


@app.view("email_settings_modal")
def handle_email_settings_modal_submission(ack, body, client, view):
    """이메일 설정 모달 제출"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        
        # 입력값 추출
        values = view["state"]["values"]
        high_priority_email = values["high_priority_email_block"]["high_priority_email_input"]["value"] or ""
        medium_priority_email = values["medium_priority_email_block"]["medium_priority_email_input"]["value"] or ""
        external_user_email = values["external_user_email_block"]["external_user_email_input"]["value"] or ""
        
        # 이메일 검증
        errors = {}
        
        if high_priority_email.strip() and not validate_email(high_priority_email):
            errors["high_priority_email_block"] = "올바른 이메일 형식을 입력해주세요."
        
        if medium_priority_email.strip() and not validate_email(medium_priority_email):
            errors["medium_priority_email_block"] = "올바른 이메일 형식을 입력해주세요."
            
        if external_user_email.strip() and not validate_email(external_user_email):
            errors["external_user_email_block"] = "올바른 이메일 형식을 입력해주세요."
        
        if errors:
            ack({
                "response_action": "errors",
                "errors": errors
            })
            return
        
        # 설정 저장
        user_config = {
            "high_priority_email": high_priority_email.strip(),
            "medium_priority_email": medium_priority_email.strip(),
            "external_user_email": external_user_email.strip()
        }
        set_user_email_config(user_id, user_config)
        
        # 성공 메시지 전송
        try:
            client.chat_postMessage(
                channel=user_id,
                text="✅ 이메일 설정이 저장되었습니다!",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "✅ *이메일 설정이 저장되었습니다!*"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*High Priority:*\n`{high_priority_email or '없음'}`"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Medium Priority:*\n`{medium_priority_email or '없음'}`"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*외부 사용자:*\n`{external_user_email or '없음'}`"
                            },
                            {
                                "type": "mrkdwn",
                                "text": " "
                            }
                        ]
                    }
                ]
            )
        except SlackApiError as e:
            logger.error(f"Failed to send confirmation message: {e.response['error']}")
        
        # App Home 업데이트 (이벤트 재발생시킴)
        try:
            client.views_publish(user_id=user_id, view={"type": "home", "blocks": []})
        except:
            pass
        
    except Exception as e:
        logger.error(f"Error handling email settings modal submission: {str(e)}")


@app.action("create_custom_case")
def handle_create_custom_case(ack, body, client):
    """커스텀 케이스 생성 버튼"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        
        # 커스텀 케이스 생성 모달 열기
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "custom_case_modal",
                "title": {
                    "type": "plain_text",
                    "text": "🎯 커스텀 케이스 생성"
                },
                "submit": {
                    "type": "plain_text", 
                    "text": "생성"
                },
                "close": {
                    "type": "plain_text",
                    "text": "취소"
                },
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "case_name_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "case_name_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "예: custom-integration-bug"
                            }
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "케이스 이름"
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "priority_block",
                        "element": {
                            "type": "static_select",
                            "action_id": "priority_select",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "우선순위 선택"
                            },
                            "options": [
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "🚨 High Priority"
                                    },
                                    "value": "high"
                                },
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "📋 Medium Priority"
                                    },
                                    "value": "medium"
                                }
                            ]
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "우선순위"
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "priority_email_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "priority_email_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "우선순위에 따라 초대할 이메일 (선택사항)"
                            }
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "Priority 사용자 이메일"
                        },
                        "optional": True
                    },
                    {
                        "type": "input",
                        "block_id": "external_email_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "external_email_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "외부 사용자 이메일 (선택사항)"
                            }
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "외부 사용자 이메일"
                        },
                        "optional": True
                    },
                    {
                        "type": "input",
                        "block_id": "additional_emails_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "additional_emails_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "user1@example.com, user2@example.com"
                            },
                            "multiline": True
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "추가 이메일들 (쉼표로 구분)"
                        },
                        "optional": True
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "💡 빈 칸으로 두면 개인 설정값을 사용합니다. 외부 사용자는 Slack Connect로 자동 초대됩니다."
                            }
                        ]
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening custom case modal: {str(e)}")


@app.view("custom_case_modal")
def handle_custom_case_modal_submission(ack, body, client, view):
    """커스텀 케이스 모달 제출"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        values = view["state"]["values"]
        
        # 입력값 추출
        case_name = values["case_name_block"]["case_name_input"]["value"]
        priority = values["priority_block"]["priority_select"]["selected_option"]["value"]
        priority_email = values.get("priority_email_block", {}).get("priority_email_input", {}).get("value", "").strip()
        external_email = values.get("external_email_block", {}).get("external_email_input", {}).get("value", "").strip()
        additional_emails = values.get("additional_emails_block", {}).get("additional_emails_input", {}).get("value", "").strip()
        
        # 입력값 검증
        errors = {}
        
        if not case_name or not case_name.strip():
            errors["case_name_block"] = "케이스 이름을 입력해주세요."
        
        if priority_email and not validate_email(priority_email):
            errors["priority_email_block"] = "올바른 이메일 형식을 입력해주세요."
            
        if external_email and not validate_email(external_email):
            errors["external_email_block"] = "올바른 이메일 형식을 입력해주세요."
        
        # 추가 이메일 검증
        if additional_emails:
            email_list = [email.strip() for email in additional_emails.split(",") if email.strip()]
            for email in email_list:
                if not validate_email(email):
                    errors["additional_emails_block"] = f"올바르지 않은 이메일 형식: {email}"
                    break
        
        if errors:
            ack({
                "response_action": "errors",
                "errors": errors
            })
            return
        
        case_name = case_name.strip()
        
        # 커스텀 이메일 설정 구성
        user_config = get_user_email_config(user_id)
        custom_emails = {
            "high_priority_email": priority_email if priority_email else user_config.get("high_priority_email", ""),
            "medium_priority_email": priority_email if priority_email else user_config.get("medium_priority_email", ""),
            "external_user_email": external_email if external_email else user_config.get("external_user_email", ""),
            "additional_emails": additional_emails
        }
        
        # 자동화 실행
        result = automator.execute_case_automation(case_name, priority, user_id, custom_emails)
        
        # 결과를 사용자에게 DM으로 전송
        blocks = create_result_blocks(result)
        
        try:
            client.chat_postMessage(
                channel=user_id,
                text=f"커스텀 케이스 자동화 {'완료' if result['success'] else '실패'}",
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
        logger.error(f"Error handling custom case modal submission: {str(e)}")


@app.action("create_high_priority_case")
def handle_high_priority_case(ack, body, client):
    """High Priority 케이스 생성 버튼"""
    ack()
    
    try:
        user_id = body["user"]["id"]
        user_config = get_user_email_config(user_id)
        
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
                            "text": f"*High Priority 케이스 설정:*\n• Priority 사용자: `{user_config.get('high_priority_email', '설정되지 않음')}`\n• 외부 사용자: `{user_config.get('external_user_email', '설정되지 않음')}`\n• 채널은 공개로 생성됩니다"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "💡 이메일 설정을 변경하려면 홈 탭의 '⚙️ 이메일 설정' 버튼을 사용하세요."
                            }
                        ]
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
        user_config = get_user_email_config(user_id)
        
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
                            "text": f"*Medium Priority 케이스 설정:*\n• Priority 사용자: `{user_config.get('medium_priority_email', '설정되지 않음')}`\n• 외부 사용자: `{user_config.get('external_user_email', '설정되지 않음')}`\n• 채널은 공개로 생성됩니다"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "💡 이메일 설정을 변경하려면 홈 탭의 '⚙️ 이메일 설정' 버튼을 사용하세요."
                            }
                        ]
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening medium priority modal: {str(e)}")


@app.view("case_creation_modal")
def handle_case_creation_modal_submission(ack, body, client, view):
    """케이스 생성 모달 제출 (High/Medium Priority)"""
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
        
        # 자동화 실행 (사용자 설정 이메일 사용)
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
    
    # 초대 통계 추가
    total_internal = len(internal_invites)
    total_external = len(external_invites)
    successful_internal = sum(1 for invite in internal_invites if invite["success"])
    successful_external = sum(1 for invite in external_invites if invite["success"])
    
    if total_internal > 0 or total_external > 0:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"📊 초대 결과: 내부 {successful_internal}/{total_internal}, 외부 {successful_external}/{total_external}"
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