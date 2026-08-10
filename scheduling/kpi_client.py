"""
KPI (EEMSportedu) bilan HTTP aloqa — o'qituvchi jurnalidagi davomat
ma'lumotini o'qish uchun.

Yo'nalish: LMS = MIJOZ, KPI = SERVER (`INTEGRATION_LMS.md`, 6-bo'lim,
shartnomani KPI tomoni taqdim etadi). Bu boshqa integratsiya yo'nalishidan
(`academic/integration_views.py` — u yerda KPI bizni chaqiradi, guruh/
kunlik biriktiruv eksporti) FARQLI: bu yerda BIZ chaqiramiz.

Nega alohida fayl: `academic/integration_views.py` dagi kabi — timeout/xato
formatlash/logging bir joyda bo'lsa, view'lar sodda qoladi.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class KPIError(Exception):
    """KPI bilan aloqada xato — foydalanuvchiga ko'rsatiladigan xabar bilan."""


def fetch_attendance(group_code, date):
    """KPI'dan (group_code, date) uchun kunlik davomat ro'yxatini oladi.

    `group_code` — bizning `Group.external_code` (UUID). KPI import paytida
    (5-bo'lim) buni o'zining `Group.lms_group_code` sifatida saqlab qo'ygan,
    shuning uchun to'g'ridan-to'g'ri, konvertatsiyasiz mos keladi.

    Javob KUN darajasida — bitta tinglovchiga bitta check-in vaqti (para
    darajasida emas). Bir kunda bir necha para bo'lsa, chaqiruvchi (view)
    shu natijani har bir para uchun alohida ishlatadi.
    """
    base = (getattr(settings, 'KPI_BASE_URL', '') or '').rstrip('/')
    key = getattr(settings, 'KPI_API_KEY', '') or ''
    if not base or not key:
        raise KPIError(
            "KPI integratsiyasi sozlanmagan (.env dagi KPI_BASE_URL / "
            "KPI_API_KEY). Administratordan so'rang."
        )
    url = f"{base}/api/integration/attendance/"
    try:
        r = requests.get(
            url,
            params={'group_code': str(group_code), 'date': date.isoformat()},
            headers={'Authorization': f'Api-Key {key}'},
            timeout=getattr(settings, 'KPI_TIMEOUT', 15),
        )
    except requests.Timeout:
        raise KPIError("KPI javob bermadi (vaqt tugadi). Keyinroq urinib ko'ring.")
    except requests.RequestException as e:
        logger.exception("KPI bilan aloqa xatosi")
        raise KPIError(f"KPI bilan aloqa o'rnatilmadi: {e}")

    if r.status_code == 403:
        raise KPIError("KPI kaliti qabul qilinmadi. Administratordan so'rang.")
    if r.status_code == 404:
        raise KPIError(
            "Bu guruh KPI'da topilmadi — hali import qilinmagan bo'lishi mumkin."
        )
    if r.status_code == 400:
        raise KPIError(f"KPI so'rovni rad etdi: {r.text[:200]}")
    if r.status_code != 200:
        raise KPIError(f"KPI kutilmagan javob qaytardi ({r.status_code}).")

    try:
        return r.json()
    except ValueError:
        raise KPIError("KPI'dan noto'g'ri formatdagi javob keldi.")
