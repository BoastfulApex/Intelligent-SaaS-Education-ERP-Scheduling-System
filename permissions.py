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


class IsEduAdminOrMethodist(BasePermission):
    """
    Yo'nalish (Major) va O'quv reja (Curriculum) uchun — edu_admin bilan bir qatorda
    methodist ('O'quv jarayonini metodik ta'minlash bo'limi') ham to'liq CRUD qila oladi.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
            User.Role.EDU_ADMIN,
            User.Role.METHODIST,
        )


class IsEduAdminWriteMethodistRead(BasePermission):
    """
    Fanlar/Guruhlar/Smenalar/Guruh biriktiruv uchun — edu_admin+ to'liq yozadi,
    methodist esa faqat o'qiydi (menyuda "O'quv jarayoni" guruhi to'liq ko'rinsin,
    lekin yozish faqat Yo'nalish/O'quv reja sahifalarida bo'lsin degan talab).
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ORG_ADMIN,
            User.Role.EDU_ADMIN,
        ):
            return True
        if request.user.role == User.Role.METHODIST and request.method in SAFE_METHODS:
            return True
        return False


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
