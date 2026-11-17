from django.urls import re_path

from .consumers import DirectChatConsumer, NotificationConsumer, RoomChatConsumer

UUID = r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"

websocket_urlpatterns = [
    re_path(rf"^ws/chat/direct/(?P<employee_id>{UUID})/$", DirectChatConsumer.as_asgi()),
    re_path(r"^ws/chat/(?P<room_name>[A-Za-z0-9_-]{1,50})/$", RoomChatConsumer.as_asgi()),
    re_path(r"^ws/notifications/$", NotificationConsumer.as_asgi()),
]
