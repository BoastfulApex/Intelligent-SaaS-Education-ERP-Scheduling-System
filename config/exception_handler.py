"""DRF xato javoblariga mashina o'qiy oladigan `code` qo'shadi.

Standart DRF faqat `{"detail": "..."}` qaytaradi — matn esa o'zbekcha va
o'zgarishi mumkin, ya'ni tashqi tizim (KPI) unga tayana olmaydi. `code`
barqaror: `invalid_key`, `inactive_client`, `scope_denied`, `throttled`.
"""
from rest_framework.views import exception_handler as drf_handler


def exception_handler(exc, context):
    response = drf_handler(exc, context)
    if response is None:
        return None
    detail = response.data.get('detail') if isinstance(response.data, dict) else None
    code = getattr(detail, 'code', None)
    if code and isinstance(response.data, dict) and 'code' not in response.data:
        response.data['code'] = code
    return response
