from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import AccessToken

from config.asgi import application

from .factories import make_employee


def token_for(user) -> str:
    return str(AccessToken.for_user(user))


class ChatTests(TransactionTestCase):
    async def connect(self, path, user=None):
        query = f"?token={token_for(user)}" if user else ""
        comm = WebsocketCommunicator(application, path + query, headers=[(b"origin", b"http://localhost")])
        connected, code = await comm.connect()
        return comm, connected, code

    async def test_rejects_anonymous(self):
        comm, connected, code = await self.connect("/ws/chat/general/")
        self.assertFalse(connected)
        self.assertEqual(code, 4001)

    async def test_room_broadcast(self):
        from asgiref.sync import sync_to_async

        alice = await sync_to_async(make_employee)()
        bob = await sync_to_async(make_employee)()
        a, ok_a, _ = await self.connect("/ws/chat/ward-1/", alice)
        b, ok_b, _ = await self.connect("/ws/chat/ward-1/", bob)
        self.assertTrue(ok_a and ok_b)
        # drain join events
        await a.receive_json_from()  # alice joined
        await a.receive_json_from()  # bob joined
        await b.receive_json_from()  # bob joined

        await a.send_json_to({"type": "message", "message": "hello ward"})
        got = await b.receive_json_from()
        self.assertEqual(got["type"], "message")
        self.assertEqual(got["message"], "hello ward")
        self.assertEqual(got["sender"]["employee_id"], str(alice.pk))
        echo = await a.receive_json_from()  # sender receives its own broadcast too
        self.assertEqual(echo["message"], "hello ward")

        await a.send_json_to({"message": "   "})
        err = await a.receive_json_from()
        self.assertEqual(err["type"], "error")
        await a.disconnect()
        await b.disconnect()

    async def test_direct_chat_only_between_related_people(self):
        from asgiref.sync import sync_to_async

        manager = await sync_to_async(make_employee)()
        nurse = await sync_to_async(make_employee)(manager_employee=manager)
        stranger = await sync_to_async(make_employee)()

        _, connected, code = await self.connect(f"/ws/chat/direct/{nurse.pk}/", stranger)
        self.assertFalse(connected)
        self.assertEqual(code, 4003)

        n, ok, _ = await self.connect(f"/ws/chat/direct/{manager.pk}/", nurse)
        self.assertTrue(ok)
        notif, ok_n, _ = await self.connect("/ws/notifications/", manager)
        self.assertTrue(ok_n)
        await n.receive_json_from()  # own join event
        await n.send_json_to({"message": "can we talk?"})
        msg = await n.receive_json_from()
        self.assertEqual(msg["message"], "can we talk?")
        pushed = await notif.receive_json_from()
        self.assertEqual(pushed["kind"], "direct_message")
        self.assertEqual(pushed["preview"], "can we talk?")
        await n.disconnect()
        await notif.disconnect()
