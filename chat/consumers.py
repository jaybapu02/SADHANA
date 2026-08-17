import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Conversation, Message

# In-process presence registry (single-process dev server).
ONLINE_USERS = set()


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """Real-time chat between a linked Parent and Child.

    The user opens one WebSocket and is subscribed to all of their own
    conversations. Every message/typing/read/presence event is delivered to
    both participants of the conversation group only.
    """

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Groups per conversation this user may participate in.
        self.group_names = []
        conversations = await self._user_conversations()
        for conv in conversations:
            group = f"chat_{conv['id']}"
            self.group_names.append(group)
            await self.channel_layer.group_add(group, self.channel_name)

        ONLINE_USERS.add(self.user.id)

        await self.accept()
        await self.send_json({"type": "connected", "conversations": conversations})
        await self._broadcast_presence(True)

    async def disconnect(self, code):
        if getattr(self, "user", None) and self.user.is_authenticated:
            ONLINE_USERS.discard(self.user.id)
            await self._broadcast_presence(False)
        if hasattr(self, "group_names"):
            for group in self.group_names:
                await self.channel_layer.group_discard(group, self.channel_name)

    @sync_to_async
    def _conversations_sync(self):
        convs = list(
            Conversation.objects.filter(
                parent=self.user
            ).select_related("parent", "child")
        ) + list(
            Conversation.objects.filter(
                child=self.user
            ).select_related("parent", "child")
        )
        return [
            {
                "id": c.id,
                "other_id": c.other_participant(self.user).id,
                "other_name": c.other_participant(self.user).username,
                "other_role": c.other_participant(self.user).role,
                "online": c.other_participant(self.user).id in ONLINE_USERS,
            }
            for c in convs
        ]

    async def _user_conversations(self):
        return await self._conversations_sync()

    async def _broadcast_presence(self, online):
        for group in self.group_names:
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.presence",
                    "payload": {"user_id": self.user.id, "online": online},
                },
            )

    async def receive_json(self, content, **kwargs):
        action = content.get("action")

        if action == "typing":
            await self._handle_typing(content)
        elif action == "mark_read":
            await self._handle_mark_read(content)
        elif action == "message":
            await self._handle_message(content)
        else:
            await self.send_json({"type": "error", "message": "Unknown action."})

    # ── Helpers ────────────────────────────────────────────────────────

    @sync_to_async
    def _get_conversation(self, conv_id):
        """Return the conversation only if this user is a participant."""
        conv = Conversation.objects.select_related("parent", "child").filter(
            id=conv_id
        ).first()
        if not conv or not conv.is_participant(self.user):
            return None
        return conv

    async def _handle_message(self, content):
        conv_id = content.get("conversation_id")
        text = (content.get("text") or "").strip()
        if not conv_id or not text:
            await self.send_json({"type": "error", "message": "Missing conversation_id or text."})
            return
        if len(text) > 2000:
            await self.send_json({"type": "error", "message": "Message too long (max 2000 chars)."})
            return

        conv = await self._get_conversation(conv_id)
        if not conv:
            await self.send_json({"type": "error", "message": "Conversation not found."})
            return

        receiver = conv.other_participant(self.user)
        msg = await Message.objects.acreate(
            conversation=conv,
            sender=self.user,
            receiver=receiver,
            text=text,
        )
        conv.last_message_at = msg.created_at
        await conv.asave(update_fields=["last_message_at"])

        payload = {
            "type": "chat_message",
            "id": msg.id,
            "conversation_id": conv.id,
            "sender_id": self.user.id,
            "sender_name": self.user.username,
            "text": text,
            "is_read": False,
            "created_at": msg.created_at.isoformat(),
        }
        await self.channel_layer.group_send(
            f"chat_{conv.id}", {"type": "chat.message", "payload": payload}
        )

    async def _handle_typing(self, content):
        conv_id = content.get("conversation_id")
        conv = await self._get_conversation(conv_id)
        if not conv:
            return
        await self.channel_layer.group_send(
            f"chat_{conv.id}",
            {
                "type": "chat.typing",
                "payload": {
                    "conversation_id": conv.id,
                    "user_id": self.user.id,
                    "user_name": self.user.username,
                },
            },
        )

    async def _handle_mark_read(self, content):
        conv_id = content.get("conversation_id")
        conv = await self._get_conversation(conv_id)
        if not conv:
            return
        # Mark all messages addressed to this user as read.
        count = await Message.objects.filter(
            conversation=conv, receiver=self.user, is_read=False
        ).aupdate(is_read=True)
        if count:
            await self.channel_layer.group_send(
                f"chat_{conv.id}",
                {
                    "type": "chat.read",
                    "payload": {
                        "conversation_id": conv.id,
                        "reader_id": self.user.id,
                    },
                },
            )

    # ── Group message handlers ─────────────────────────────────────────

    async def chat_message(self, event):
        await self.send_json(event["payload"])

    async def chat_typing(self, event):
        payload = event["payload"]
        # Do not echo the typing event back to the person typing.
        if payload["user_id"] != self.user.id:
            await self.send_json({"type": "typing", **payload})

    async def chat_read(self, event):
        payload = event["payload"]
        await self.send_json({"type": "read", **payload})

    async def chat_presence(self, event):
        await self.send_json({"type": "presence", **event["payload"]})