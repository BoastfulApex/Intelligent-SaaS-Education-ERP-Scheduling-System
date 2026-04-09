from rest_framework.permissions import BasePermission, SAFE_METHODS
from accounts.models import User


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.SUPER_ADMIN


class IsOrgAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
        )


class IsEduAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
            User.Role.EDU_ADMIN,
        )


class IsDeptManager(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
            User.Role.DEPARTMENT_MANAGER,
        )


class IsOrgAdminOrReadOnly(BasePermission):
    """Org admin yoza oladi, qolganlar faqat o'qiydi."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
        )


class IsEduAdminOrReadOnly(BasePermission):
    """Edu admin yoza oladi, qolganlar faqat o'qiydi."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
            User.Role.EDU_ADMIN,
        )


class IsDeptManagerOrReadOnly(BasePermission):
    """Dept manager yoza oladi, qolganlar faqat o'qiydi."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
            User.Role.DEPARTMENT_MANAGER,
        )


class IsTeacherOwner(BasePermission):
    """Teacher faqat o'z ma'lumotlarini ko'ra oladi."""
    def has_object_permission(self, request, view, obj):
        if request.user.role != User.Role.TEACHER:
            return True
        # ScheduleEntry uchun
        if hasattr(obj, 'teacher'):
            return obj.teacher.user == request.user
        return False
