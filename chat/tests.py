import json

from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase

from relationships.models import ConnectionRequest
from .models import Conversation, Message

User = get_user_model()


def make_users():
    parent_a = User.objects.create_user(username="parent_a", password="pass", role="PARENT")
    parent_b = User.objects.create_user(username="parent_b", password="pass", role="PARENT")
    child_a = User.objects.create_user(username="child_a", password="pass", role="CHILD")
    child_b = User.objects.create_user(username="child_b", password="pass", role="CHILD")
    return parent_a, parent_b, child_a, child_b


def link(parent, child):
    return ConnectionRequest.objects.create(parent=parent, child=child, status="ACCEPTED")


def login_cookie(client, username):
    assert client.login(username=username, password="pass")
    return client.cookies["sessionid"].value


def cookie_headers(session_id):
    return [(b"cookie", f"sessionid={session_id}".encode())]


class ChatAuthorizationMatrixTests(TestCase):
    """Parent A <-> Child A only. All other combinations must be rejected."""

    def setUp(self):
        self.parent_a, self.parent_b, self.child_a, self.child_b = make_users()
        link(self.parent_a, self.child_a)
        link(self.parent_b, self.child_b)
        self.conv_a = Conversation.objects.create(parent=self.parent_a, child=self.child_a)
        self.conv_b = Conversation.objects.create(parent=self.parent_b, child=self.child_b)

    def test_only_linked_pair_can_converse(self):
        self.assertTrue(self.conv_a.is_participant(self.parent_a))
        self.assertTrue(self.conv_a.is_participant(self.child_a))
        self.assertFalse(self.conv_a.is_participant(self.parent_b))
        self.assertFalse(self.conv_a.is_participant(self.child_b))

    def test_api_messages_forbidden_for_outsiders(self):
        self.client.login(username="parent_a", password="pass")
        r = self.client.get(f"/chat/api/conversations/{self.conv_b.id}/messages/")
        self.assertEqual(r.status_code, 403)
        self.client.login(username="child_b", password="pass")
        r = self.client.get(f"/chat/api/conversations/{self.conv_a.id}/messages/")
        self.assertEqual(r.status_code, 403)

    def test_api_mark_read_forbidden_for_outsiders(self):
        self.client.login(username="child_a", password="pass")
        r = self.client.post(f"/chat/api/conversations/{self.conv_b.id}/mark-read/")
        self.assertEqual(r.status_code, 403)

    def test_api_send_forbidden_for_outsiders(self):
        self.client.login(username="parent_b", password="pass")
        r = self.client.post(
            f"/chat/api/conversations/{self.conv_a.id}/send/",
            data=json.dumps({"text": "hi"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_quick_conversation_only_for_linked(self):
        # Linked pair -> conversation returned/created.
        self.client.login(username="parent_a", password="pass")
        r = self.client.get(f"/chat/api/quick/{self.child_a.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("conversation_id", r.json())
        # Parent A <-> Child B NOT linked.
        r = self.client.get(f"/chat/api/quick/{self.child_b.id}/")
        self.assertEqual(r.status_code, 403)
        # Child A <-> Child B not allowed (child-child).
        self.client.login(username="child_a", password="pass")
        r = self.client.get(f"/chat/api/quick/{self.child_b.id}/")
        self.assertEqual(r.status_code, 403)
        # Parent A <-> Parent B not allowed (parent-parent).
        self.client.login(username="parent_a", password="pass")
        r = self.client.get(f"/chat/api/quick/{self.parent_b.id}/")
        self.assertEqual(r.status_code, 403)

    def test_conversation_list_only_own(self):
        self.client.login(username="child_a", password="pass")
        r = self.client.get("/chat/api/conversations/")
        convs = r.json()["conversations"]
        self.assertEqual([c["id"] for c in convs], [self.conv_a.id])
        self.assertEqual([c["other_name"] for c in convs], ["parent_a"])


class ChatMessageFlowTests(TestCase):
    def setUp(self):
        self.parent_a, self.parent_b, self.child_a, self.child_b = make_users()
        link(self.parent_a, self.child_a)
        link(self.parent_b, self.child_b)
        self.conv_a = Conversation.objects.create(parent=self.parent_a, child=self.child_a)

    def _send(self, client, conv_id, text, **extra):
        return client.post(
            f"/chat/api/conversations/{conv_id}/send/",
            data=json.dumps({"text": text, **extra}),
            content_type="application/json",
        )

    def test_http_send_and_history(self):
        self.client.login(username="child_a", password="pass")
        r = self.client.post(
            f"/chat/api/conversations/{self.conv_a.id}/send/",
            data=json.dumps({"text": "Can you help me with math?"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)

        self.client.login(username="parent_a", password="pass")
        r = self.client.get(f"/chat/api/conversations/{self.conv_a.id}/messages/")
        msgs = r.json()["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["text"], "Can you help me with math?")
        self.assertEqual(msgs[0]["sender_name"], "child_a")
        self.assertFalse(msgs[0]["is_read"])

        # Unread counts: the receiver (parent) sees 1 unread; sender sees 0.
        self.client.login(username="child_a", password="pass")
        r = self.client.get("/chat/api/unread-count/")
        self.assertEqual(r.json()["unread_count"], 0)
        self.client.login(username="parent_a", password="pass")
        r = self.client.get("/chat/api/unread-count/")
        self.assertEqual(r.json()["unread_count"], 1)

    def test_mark_read(self):
        Message.objects.create(
            conversation=self.conv_a, sender=self.parent_a,
            receiver=self.child_a, text="Keep going!",
        )
        self.client.login(username="child_a", password="pass")
        r = self.client.post(f"/chat/api/conversations/{self.conv_a.id}/mark-read/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["marked"], 1)
        self.assertFalse(
            Message.objects.filter(conversation=self.conv_a, is_read=False).exists()
        )

    def test_chat_page_renders(self):
        self.client.login(username="parent_a", password="pass")
        r = self.client.get("/chat/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Conversations")
        self.client.login(username="child_a", password="pass")
        r = self.client.get("/chat/")
        self.assertEqual(r.status_code, 200)


class ChatConsumerTests(TestCase):
    def setUp(self):
        self.parent_a, self.parent_b, self.child_a, self.child_b = make_users()
        link(self.parent_a, self.child_a)
        link(self.parent_b, self.child_b)
        self.conv_a = Conversation.objects.create(parent=self.parent_a, child=self.child_a)
        self.conv_b = Conversation.objects.create(parent=self.parent_b, child=self.child_b)

    async def test_consumer_requires_login(self):
        comm = WebsocketCommunicator(user_injector_app(None), "/ws/chat/")
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_realtime_message_between_parent_and_child(self):
        comm_a = WebsocketCommunicator(user_injector_app(self.child_a), "/ws/chat/")
        connected, _ = await comm_a.connect()
        self.assertTrue(connected)
        # First event is the 'connected' handshake.
        connected_msg = await comm_a.receive_json_from()
        self.assertEqual(connected_msg["type"], "connected")
        self.assertEqual(connected_msg["conversations"][0]["other_name"], "parent_a")
        await comm_a.receive_json_from()  # presence: child_a online (own)

        comm_p = WebsocketCommunicator(user_injector_app(self.parent_a), "/ws/chat/")
        connected, _ = await comm_p.connect()
        self.assertTrue(connected)
        await comm_p.receive_json_from()  # connected
        await comm_p.receive_json_from()  # presence: parent_a online (own)
        await comm_a.receive_json_from()  # presence: parent_a online

        await comm_a.send_json_to({
            "action": "message",
            "conversation_id": self.conv_a.id,
            "text": "💪 Keep going!",
        })
        # Sender receives its own echo; the parent receives the message too.
        echo = await comm_a.receive_json_from()
        self.assertEqual(echo["type"], "chat_message")
        self.assertEqual(echo["text"], "💪 Keep going!")
        got = await comm_p.receive_json_from()
        self.assertEqual(got["type"], "chat_message")
        self.assertEqual(got["sender_name"], "child_a")

        # Persisted in DB for history.
        from asgiref.sync import sync_to_async
        exists = await sync_to_async(
            lambda: Message.objects.filter(
                conversation=self.conv_a, sender=self.child_a,
                receiver=self.parent_a, text="💪 Keep going!",
            ).exists()
        )()
        self.assertTrue(exists)

    async def test_typing_indicator_broadcast(self):
        comm_a = WebsocketCommunicator(user_injector_app(self.child_a), "/ws/chat/")
        await comm_a.connect()
        await comm_a.receive_json_from()
        await comm_a.receive_json_from()  # presence: child_a online (own)
        comm_p = WebsocketCommunicator(user_injector_app(self.parent_a), "/ws/chat/")
        await comm_p.connect()
        await comm_p.receive_json_from()
        await comm_p.receive_json_from()  # presence: parent_a online (own)
        await comm_a.receive_json_from()  # presence: parent_a online

        await comm_a.send_json_to({"action": "typing", "conversation_id": self.conv_a.id})
        # Parent receives typing; child (typer) does not.
        got = await comm_p.receive_json_from()
        self.assertEqual(got["type"], "typing")
        self.assertEqual(got["user_id"], self.child_a.id)

    async def test_presence_online_offline(self):
        comm_a = WebsocketCommunicator(user_injector_app(self.child_a), "/ws/chat/")
        await comm_a.connect()
        await comm_a.receive_json_from()
        await comm_a.receive_json_from()  # presence: child_a online (own)
        comm_p = WebsocketCommunicator(user_injector_app(self.parent_a), "/ws/chat/")
        await comm_p.connect()
        await comm_p.receive_json_from()
        await comm_p.receive_json_from()  # presence: parent_a online (own)

        presence = await comm_a.receive_json_from()
        self.assertEqual(presence["type"], "presence")
        self.assertTrue(presence["online"])

        await comm_p.disconnect()
        presence = await comm_a.receive_json_from()
        self.assertEqual(presence["type"], "presence")
        self.assertFalse(presence["online"])

    async def test_cross_pair_blocked_on_websocket(self):
        # Child B tries to message Parent A's conversation -> error, no leak.
        comm_b = WebsocketCommunicator(user_injector_app(self.child_b), "/ws/chat/")
        await comm_b.connect()
        await comm_b.receive_json_from()
        await comm_b.receive_json_from()  # presence: child_b online (own)
        await comm_b.send_json_to({
            "action": "message",
            "conversation_id": self.conv_a.id,
            "text": "trespass",
        })
        got = await comm_b.receive_json_from()
        self.assertEqual(got["type"], "error")
        from asgiref.sync import sync_to_async
        self.assertFalse(await sync_to_async(
            lambda: Message.objects.filter(conversation=self.conv_a, text="trespass").exists()
        )())


class ChatFeatureTests(TestCase):
    """Edit / delete / reply / attachments / search / pagination / delivery."""

    def setUp(self):
        self.parent_a, self.parent_b, self.child_a, self.child_b = make_users()
        link(self.parent_a, self.child_a)
        link(self.parent_b, self.child_b)
        self.conv_a = Conversation.objects.create(parent=self.parent_a, child=self.child_a)
        self.conv_b = Conversation.objects.create(parent=self.parent_b, child=self.child_b)

    def _send(self, client, conv_id, text, **extra):
        return client.post(
            f"/chat/api/conversations/{conv_id}/send/",
            data=json.dumps({"text": text, **extra}),
            content_type="application/json",
        )

    def _post(self, client, url, data):
        return client.post(url, data=json.dumps(data), content_type="application/json")

    def test_edit_own_message(self):
        msg = Message.objects.create(
            conversation=self.conv_a, sender=self.child_a,
            receiver=self.parent_a, text="original",
        )
        self.client.login(username="child_a", password="pass")
        r = self._post(self.client, f"/chat/api/conversations/{self.conv_a.id}/edit/",
                       {"message_id": msg.id, "text": "edited text"})
        self.assertEqual(r.status_code, 200)
        msg.refresh_from_db()
        self.assertEqual(msg.text, "edited text")
        self.assertTrue(msg.is_edited)

    def test_cannot_edit_others_message(self):
        msg = Message.objects.create(
            conversation=self.conv_a, sender=self.parent_a,
            receiver=self.child_a, text="from parent",
        )
        self.client.login(username="child_a", password="pass")
        r = self._post(self.client, f"/chat/api/conversations/{self.conv_a.id}/edit/",
                       {"message_id": msg.id, "text": "hacked"})
        self.assertEqual(r.status_code, 403)
        msg.refresh_from_db()
        self.assertEqual(msg.text, "from parent")

    def test_cannot_edit_in_other_conversation(self):
        msg = Message.objects.create(
            conversation=self.conv_b, sender=self.parent_b,
            receiver=self.child_b, text="other pair",
        )
        self.client.login(username="parent_a", password="pass")
        r = self._post(self.client, f"/chat/api/conversations/{self.conv_b.id}/edit/",
                       {"message_id": msg.id, "text": "hacked"})
        self.assertEqual(r.status_code, 403)

    def test_delete_own_message_tombstone(self):
        msg = Message.objects.create(
            conversation=self.conv_a, sender=self.child_a,
            receiver=self.parent_a, text="remove me",
        )
        self.client.login(username="child_a", password="pass")
        r = self._post(self.client, f"/chat/api/conversations/{self.conv_a.id}/delete/",
                       {"message_id": msg.id})
        self.assertEqual(r.status_code, 200)
        msg.refresh_from_db()
        self.assertTrue(msg.is_deleted)
        self.assertEqual(msg.text, "")

    def test_cannot_delete_others_message(self):
        msg = Message.objects.create(
            conversation=self.conv_a, sender=self.parent_a,
            receiver=self.child_a, text="keep me",
        )
        self.client.login(username="child_a", password="pass")
        r = self._post(self.client, f"/chat/api/conversations/{self.conv_a.id}/delete/",
                       {"message_id": msg.id})
        self.assertEqual(r.status_code, 403)
        msg.refresh_from_db()
        self.assertFalse(msg.is_deleted)

    def test_reply_wires_parent_message(self):
        original = Message.objects.create(
            conversation=self.conv_a, sender=self.parent_a,
            receiver=self.child_a, text="How's the math homework?",
        )
        self.client.login(username="child_a", password="pass")
        r = self._send(self.client, self.conv_a.id, "Almost done!", reply_to_id=original.id)
        self.assertEqual(r.status_code, 200)
        reply = Message.objects.filter(conversation=self.conv_a, text="Almost done!").first()
        self.assertEqual(reply.parent_msg_id, original.id)
        self.assertIsNotNone(r.json()["reply_to"])

    def test_upload_image_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        png = SimpleUploadedFile(
            "plot.png", b"\x89PNG\r\n\x1a\n fake-png-bytes",
            content_type="image/png",
        )
        self.client.login(username="parent_a", password="pass")
        r = self.client.post(
            f"/chat/api/conversations/{self.conv_a.id}/upload/",
            {"file": png},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["attachment_type"], "image")
        self.assertTrue(data["attachment_url"].endswith("plot.png"))
        msg = Message.objects.get(id=data["id"])
        self.assertTrue(msg.attachment.name.endswith("plot.png"))

    def test_upload_rejects_unsupported_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        exe = SimpleUploadedFile("virus.exe", b"MZ\x90\x00", content_type="application/x-msdownload")
        self.client.login(username="child_a", password="pass")
        r = self.client.post(
            f"/chat/api/conversations/{self.conv_a.id}/upload/",
            {"file": exe},
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Message.objects.filter(conversation=self.conv_a).exists())

    def test_upload_forbidden_for_outsider(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        png = SimpleUploadedFile("x.png", b"png", content_type="image/png")
        self.client.login(username="parent_b", password="pass")
        r = self.client.post(
            f"/chat/api/conversations/{self.conv_a.id}/upload/",
            {"file": png},
        )
        self.assertEqual(r.status_code, 403)

    def test_search_only_in_own_conversations(self):
        Message.objects.create(
            conversation=self.conv_a, sender=self.child_a,
            receiver=self.parent_a, text="math homework discussion",
        )
        Message.objects.create(
            conversation=self.conv_b, sender=self.child_b,
            receiver=self.parent_b, text="math homework other pair",
        )
        self.client.login(username="parent_a", password="pass")
        r = self.client.get("/chat/api/search/?q=homework")
        results = r.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["conversation_id"], self.conv_a.id)

    def test_pagination_before_id(self):
        for i in range(5):
            Message.objects.create(
                conversation=self.conv_a, sender=self.parent_a,
                receiver=self.child_a, text=f"msg {i}",
            )
        self.client.login(username="child_a", password="pass")
        # Load latest page: 5 messages newest first in payload but chronological array.
        r = self.client.get(f"/chat/api/conversations/{self.conv_a.id}/messages/")
        msgs = r.json()["messages"]
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[0]["text"], "msg 0")
        self.assertEqual(msgs[-1]["text"], "msg 4")
        # Page older than the last id returns the remaining.
        r = self.client.get(
            f"/chat/api/conversations/{self.conv_a.id}/messages/?before_id={msgs[0]['id']}"
        )
        self.assertEqual(r.json()["messages"], [])

    def test_around_id_window(self):
        ids = []
        for i in range(10):
            ids.append(Message.objects.create(
                conversation=self.conv_a, sender=self.parent_a,
                receiver=self.child_a, text=f"around {i}",
            ).id)
        self.client.login(username="child_a", password="pass")
        r = self.client.get(
            f"/chat/api/conversations/{self.conv_a.id}/messages/?around_id={ids[7]}"
        )
        texts = [m["text"] for m in r.json()["messages"]]
        self.assertIn("around 7", texts)
        self.assertIn("around 2", texts)  # window covers earlier messages

    def test_delivered_flag_when_receiver_online(self):
        from .services import ONLINE_USERS
        ONLINE_USERS.add(self.parent_a.id)
        try:
            self.client.login(username="child_a", password="pass")
            r = self._send(self.client, self.conv_a.id, "are you there?")
            self.assertTrue(r.json()["is_delivered"])
        finally:
            ONLINE_USERS.discard(self.parent_a.id)

    def test_offline_chat_notification_created(self):
        from .services import ONLINE_USERS
        ONLINE_USERS.discard(self.parent_a.id)
        from notifications.models import Notification
        self.client.login(username="child_a", password="pass")
        self._send(self.client, self.conv_a.id, "hello while offline")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.parent_a, notification_type="CHAT_MESSAGE"
            ).exists()
        )


def user_injector_app(user):
    """Wrap the consumer so the given user lands in the connection scope
    (as AuthMiddlewareStack would populate it for real connections)."""
    from .consumers import ChatConsumer

    app = ChatConsumer.as_asgi()

    async def wrapped(scope, receive, send):
        scope["user"] = user
        await app(scope, receive, send)

    return wrapped


def _ws_scope(user):
    """Build a minimal scope carrying the authenticated user,
    as AuthMiddlewareStack would populate it."""
    return {"type": "websocket", "user": user if user and user.is_authenticated else None,
            "path": "/ws/chat/", "headers": []}