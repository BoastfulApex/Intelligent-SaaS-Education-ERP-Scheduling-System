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


class HasIntegrationScope(BasePermission):
    """
    Server-to-server API kalit tekshiruvi (KPI integratsiyasi).

    Header:  Authorization: Api-Key <prefix>.<secret>

    View'da `required_scope` atributi belgilanadi, masalan:
        required_scope = 'groups:read'

    MUHIM: barcha rad etishlar **403** qaytaradi, 401 emas. Sabab: DRF 401
    qaytarishi uchun `WWW-Authenticate` sarlavhasini bera oladigan
    authentication klass kerak, bu yerda esa `authentication_classes = []`
    (mashina-mijoz uchun interaktiv auth chaqirig'i ma'nosiz). Rad etish
    sababi javob tanasidagi `code` maydonida qaytadi — LMS/KPI logida
    haqiqiy sabab ko'rinishi uchun.
    """
    message = "Kalit qabul qilinmadi."
    code = 'invalid_key'

    def _deny(self, reason, code):
        # DRF `permission_denied()` da `message` va `code` atributlarini
        # o'qiydi — nomlar AYNAN shunday bo'lishi shart.
        self.message = reason
        self.code = code
        return False

    def has_permission(self, request, view):
        from organizations.models import IntegrationClient

        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header.startswith('Api-Key '):
            return self._deny("Api-Key sarlavhasi yo'q yoki formati noto'g'ri.",
                              'invalid_key')
        raw = header[len('Api-Key '):].strip()
        if raw.count('.') != 1:
            return self._deny("Kalit formati noto'g'ri (<prefix>.<secret> kutiladi).",
                              'invalid_key')
        prefix, secret = raw.split('.', 1)

        # `is_active` ALOHIDA tekshiriladi — aks holda o'chirilgan mijoz
        # "kalit topilmadi" bilan qo'shilib ketardi va logda sabab ko'rinmasdi.
        client = IntegrationClient.objects.filter(key_prefix=prefix).first()
        if client is None:
            return self._deny("Kalit topilmadi.", 'invalid_key')

        import hmac
        if not hmac.compare_digest(client.key_hash,
                                   IntegrationClient.hash_secret(secret)):
            # `compare_digest` — vaqt bo'yicha hujumdan (timing attack)
            # himoya: oddiy `==` mos kelmagan joyda darhol to'xtaydi va
            # javob vaqti orqali kalitni belgima-belgi topish mumkin bo'lardi.
            return self._deny("Kalit noto'g'ri.", 'invalid_key')

        if not client.is_active:
            return self._deny("Kalit o'chirilgan.", 'inactive_client')

        required = getattr(view, 'required_scope', None)
        if required and not client.has_scope(required):
            return self._deny(f"Kalitda '{required}' huquqi yo'q.", 'scope_denied')

        from django.utils import timezone
        IntegrationClient.objects.filter(pk=client.pk).update(
            last_used=timezone.now()
        )
        request.integration_client = client
        return True
