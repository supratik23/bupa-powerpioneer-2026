from rest_framework.routers import DefaultRouter

from .views import AppointmentViewSet, AttendanceViewSet, LeaveRequestViewSet, ShiftRosterViewSet

router = DefaultRouter()
router.register("shifts", ShiftRosterViewSet, basename="shift")
router.register("leave-requests", LeaveRequestViewSet, basename="leave-request")
router.register("attendance", AttendanceViewSet, basename="attendance")
router.register("appointments", AppointmentViewSet, basename="appointment")

urlpatterns = router.urls
