import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import ModelVersion, ModelComment

logger = logging.getLogger(__name__)


class ModelCommentConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.model_version_id = self.scope["url_route"]["kwargs"]["version_id"]
            self.room_group_name = f"model_comments_{self.model_version_id}"

            # Join room group
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)

            await self.accept()
            logger.info(
                f"WebSocket connected for model version {self.model_version_id}"
            )
        except Exception as e:
            logger.error(f"Error connecting WebSocket: {e}")
            await self.close()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message = text_data_json.get("message", "").strip()
            username = text_data_json.get("username", "")
            parent_id = text_data_json.get("parent_id", None)

            if not message or not username:
                return

            # Save comment to database
            comment_data = await self.save_comment(
                username, self.model_version_id, message, parent_id
            )

            # Only broadcast if comment was saved successfully
            if comment_data:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "comment_message",
                        "message": message,
                        "username": username,
                        "comment_id": comment_data["id"],
                        "parent_id": parent_id,
                        "timestamp": comment_data["timestamp"],
                        "timestamp_utc": comment_data["timestamp_utc"],
                        "user_role": comment_data["user_role"],
                    },
                )
        except json.JSONDecodeError:
            # Invalid JSON, ignore
            pass
        except Exception as e:
            logger.error(f"Error in receive: {e}")

    async def comment_message(self, event):
        # Send message to WebSocket
        await self.send(
            text_data=json.dumps(
                {
                    "message": event["message"],
                    "username": event["username"],
                    "comment_id": event["comment_id"],
                    "parent_id": event["parent_id"],
                    "timestamp": event["timestamp"],
                    "timestamp_utc": event.get("timestamp_utc", event["timestamp"]),
                    "user_role": event["user_role"],
                }
            )
        )

    @database_sync_to_async
    def save_comment(self, username, version_id, message, parent_id):
        try:
            user = User.objects.get(username=username)
            version = ModelVersion.objects.get(id=version_id)

            parent = None
            if parent_id:
                try:
                    parent = ModelComment.objects.get(id=parent_id)
                except ModelComment.DoesNotExist:
                    parent = None

            comment = ModelComment.objects.create(
                user=user, model_version=version, content=message, parent=parent
            )

            return {
                "id": comment.id,
                "timestamp": comment.created_at.strftime("%b %d, %Y %I:%M %p"),
                "timestamp_utc": comment.created_at.isoformat(),
                "user_role": user.profile.role,
            }
        except (User.DoesNotExist, ModelVersion.DoesNotExist) as e:
            # Log error and return None to prevent broadcasting invalid data
            logger.error(f"Error saving comment: {e}")
            return None
