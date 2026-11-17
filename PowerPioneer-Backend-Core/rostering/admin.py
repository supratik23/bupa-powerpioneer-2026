from django.contrib import admin

from .models import Attendance, LeaveRequest, ShiftRoster


@admin.register(ShiftRoster)
class ShiftRosterAdmin(admin.ModelAdmin):
    list_display = ["employee", "shift_type", "shift_start", "shift_end", "planned_hours", "actual_hours",
                    "understaffed_flag", "missed_break_flag"]
    list_filter = ["shift_type", "understaffed_flag", "missed_break_flag", "short_notice_change_flag"]
    raw_id_fields = ["employee"]


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ["employee", "leave_type", "start_date", "end_date", "status", "requested_at"]
    list_filter = ["leave_type", "status"]
    raw_id_fields = ["employee"]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["employee", "attendance_date", "attendance_status", "late_minutes", "absence_type"]
    list_filter = ["attendance_status", "absence_type"]
    raw_id_fields = ["employee"]
