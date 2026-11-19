"""
Internal endpoint for the ShiftGuard AI agent (PowerPioneer-AI/langgraph-agent).

The agent writes straight to Supabase, so Django never sees those writes. After it records an intervention, moves a
shift, decides leave or builds a briefing, it calls this endpoint so the person gets a real-time bell notification on
their personal WebSocket group (ws/notifications/), exactly like Django's own interventions.

POST /api/internal/notify/
    Header  X-Agent-Key: <AGENT_INTERNAL_KEY>
    Body    {"employee_id": "<uuid>", "payload": {"kind": "...", ...}}
"""
import hmac
import uuid

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .notifications import notify_employee

ALLOWED_KINDS = {"intervention", "shift_change", "leave_decision", "buddy_assigned", "briefing"}


@extend_schema(tags=["Internal"], exclude=True)
class AgentNotifyView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]   # checked with the shared key below

    def post(self, request):
        key = request.headers.get("X-Agent-Key", "")
        if not settings.AGENT_INTERNAL_KEY or not hmac.compare_digest(key, settings.AGENT_INTERNAL_KEY):
            return Response({"detail": "Invalid agent key."}, status=status.HTTP_403_FORBIDDEN)
        try:
            employee_id = uuid.UUID(str(request.data.get("employee_id")))
        except (TypeError, ValueError):
            return Response({"detail": "employee_id must be a UUID."}, status=status.HTTP_400_BAD_REQUEST)
        payload = request.data.get("payload")
        if not isinstance(payload, dict) or payload.get("kind") not in ALLOWED_KINDS:
            return Response({"detail": f"payload.kind must be one of {sorted(ALLOWED_KINDS)}."},
                            status=status.HTTP_400_BAD_REQUEST)
        notify_employee(employee_id, {**payload, "source": "agent"})
        return Response({"sent": True}, status=status.HTTP_202_ACCEPTED)
