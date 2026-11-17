"""Server-side push to an employee's personal WebSocket group (ws/notifications/)."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

log = logging.getLogger(__name__)


def user_group(employee_id) -> str:
    return f"user_{str(employee_id).replace('-', '')}"


def notify_employee(employee_id, payload: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(user_group(employee_id), {"type": "notify", "payload": payload})
    except Exception:  # never let a notification failure break the request
        log.exception("Failed to push notification to %s", employee_id)
