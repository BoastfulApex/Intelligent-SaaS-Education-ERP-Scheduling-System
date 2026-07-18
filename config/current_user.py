"""
Joriy so'rov (request) ga thread-local orqali kirish — AuditLog signal
handlerlariga JWT bilan autentifikatsiyalangan foydalanuvchini yetkazish uchun.

DRF autentifikatsiyasi (JWT) view dispatch bosqichida (permission tekshiruvidan
oldin) sodir bo'ladi va request.user ni xuddi shu HttpRequest obyektiga
yozadi (DRF Request.user setter orqali). Shu sabab bu yerda so'rov OBYEKTINING
o'zini saqlaymiz (qiymatini emas) — signal (post_save/post_delete) qachon
ishga tushmasin, o'sha vaqtga kelib DRF autentifikatsiyasi allaqachon
bajarilgan bo'ladi.
"""
import threading

_local = threading.local()


class CurrentRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            return self.get_response(request)
        finally:
            _local.request = None


def get_current_user():
    request = getattr(_local, 'request', None)
    if request is None:
        return None
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    return user
