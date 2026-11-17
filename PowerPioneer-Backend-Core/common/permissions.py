"""
Access rules shared across apps.

Roles are derived from the data, not from a separate role table:
  * staff (``is_staff``)            -> HR / admin, full access
  * manager of X                    -> X.manager_employee == user
  * the employee themself           -> X == user
"""
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied


def is_staff(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def is_manager_of(user, employee) -> bool:
    return bool(employee is not None and employee.manager_employee_id == user.pk)


def can_manage(user, employee) -> bool:
    """Staff, or the direct manager of ``employee``."""
    return is_staff(user) or is_manager_of(user, employee)


def can_view(user, employee) -> bool:
    """Staff, the employee themself, or their direct manager."""
    return is_staff(user) or employee.pk == user.pk or is_manager_of(user, employee)


def ensure(condition: bool, message: str = "You do not have permission to perform this action."):
    if not condition:
        raise PermissionDenied(message)


class IsStaffOrReadOnly(permissions.BasePermission):
    """Any authenticated user can read; only staff can write."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return is_staff(request.user)


class IsStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return is_staff(request.user)
