"""
WebSocket consumers.

Endpoints (see chat/routing.py):
  ws/chat/<room_name>/            group chat room, any authenticated employee
  ws/chat/direct/<employee_id>/   1:1 chat with a manager, direct report, buddy or buddy assignee
                                  (staff may message anyone)
  ws/notifications/               personal push channel (interventions, new direct messages)

Client -> server frames (JSON):
  {"type": "message", "message": "Hello"}      # "type" may be omitted
  {"type": "typing"}

Server -> client frames (JSON):
  {"type": "message", "room": ..., "message": ..., "sender": {...}, "timestamp": ...}
  {"type": "typing" | "join" | "leave", "room": ..., "sender": {...}}
  {"type": "error", "error": "..."}
  {"type": "notification", ...}

Close codes: 4001 not authenticated, 4003 not allowed, 4004 employee not found.
Messages are relayed live and not persisted (the schema has no chat table).
"""
from django.utils import timezone
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .notifications import user_group

MAX_MESSAGE_LENGTH = 2000


def _sender(user) -> dict:
    return {"employee_id": str(user.pk), "full_name": user.full_name, "email": user.email}


class BaseChatConsumer(AsyncJsonWebsocketConsumer):
    group_name: str
    room_label: str

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        if not await self.authorize():
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.channel_layer.group_send(
            self.group_name, {"type": "chat.event", "event": "join", "sender": _sender(user)}
        )

    async def authorize(self) -> bool:
        raise NotImplementedError

    async def disconnect(self, code):
        if hasattr(self, "user") and hasattr(self, "group_name"):
            await self.channel_layer.group_send(
                self.group_name, {"type": "chat.event", "event": "leave", "sender": _sender(self.user)}
            )
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "error": "Expected a JSON object."})
            return
        kind = content.get("type", "message")
        if kind == "typing":
            await self.channel_layer.group_send(
                self.group_name, {"type": "chat.event", "event": "typing", "sender": _sender(self.user)}
            )
            return
        if kind != "message":
            await self.send_json({"type": "error", "error": f"Unknown type '{kind}'."})
            return
        message = str(content.get("message", "")).strip()
        if not message:
            await self.send_json({"type": "error", "error": "Message must not be empty."})
            return
        if len(message) > MAX_MESSAGE_LENGTH:
            await self.send_json({"type": "error", "error": f"Message exceeds {MAX_MESSAGE_LENGTH} characters."})
            return
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.message",
                "message": message,
                "sender": _sender(self.user),
                "timestamp": timezone.now().isoformat(),
            },
        )
        await self.after_message(message)

    async def after_message(self, message: str):
        """Hook for subclasses."""

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        try:
            await super().receive(text_data=text_data, bytes_data=bytes_data, **kwargs)
        except ValueError:  # invalid JSON
            await self.send_json({"type": "error", "error": "Invalid JSON."})

    # -- group handlers ---------------------------------------------------
    async def chat_message(self, event):
        await self.send_json({
            "type": "message", "room": self.room_label, "message": event["message"],
            "sender": event["sender"], "timestamp": event["timestamp"],
        })

    async def chat_event(self, event):
        # don't echo your own typing indicator
        if event["event"] == "typing" and event["sender"]["employee_id"] == str(self.user.pk):
            return
        await self.send_json({"type": event["event"], "room": self.room_label, "sender": event["sender"]})


class RoomChatConsumer(BaseChatConsumer):
    async def authorize(self) -> bool:
        room = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_label = room
        self.group_name = f"chat_{room}"
        return True


class DirectChatConsumer(BaseChatConsumer):
    async def authorize(self) -> bool:
        other_id = self.scope["url_route"]["kwargs"]["employee_id"]
        other = await self._get_employee(other_id)
        if other is None:
            await self.close(code=4004)
            return False
        if not await self._may_chat(self.user, other):
            await self.close(code=4003)
            return False
        self.other = other
        a, b = sorted([str(self.user.pk).replace("-", ""), str(other.pk).replace("-", "")])
        self.group_name = f"dm_{a}_{b}"
        self.room_label = f"direct:{other.pk}"
        return True

    async def after_message(self, message: str):
        # Let the recipient know even if they are not in the conversation right now.
        await self.channel_layer.group_send(
            user_group(self.other.pk),
            {"type": "notify", "payload": {
                "kind": "direct_message", "from": _sender(self.user), "preview": message[:120],
            }},
        )

    @database_sync_to_async
    def _get_employee(self, employee_id):
        from django.core.exceptions import ValidationError

        from employees.models import Employee

        try:
            return Employee.objects.get(pk=employee_id, is_active=True)
        except (Employee.DoesNotExist, ValueError, ValidationError):
            return None

    @database_sync_to_async
    def _may_chat(self, user, other) -> bool:
        if user.pk == other.pk:
            return False
        if user.is_staff or other.is_staff:
            return True
        return (
            user.manager_employee_id == other.pk or other.manager_employee_id == user.pk
            or user.buddy_employee_id == other.pk or other.buddy_employee_id == user.pk
        )


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.group_name = user_group(user.pk)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        await self.send_json({"type": "error", "error": "This channel is receive-only."})

    async def notify(self, event):
        await self.send_json({"type": "notification", **event["payload"]})
