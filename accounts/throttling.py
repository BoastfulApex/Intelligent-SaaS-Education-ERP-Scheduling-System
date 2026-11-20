"""
Login uchun brute force himoyasi.

**Nega IP bo'yicha emas, LOGIN bo'yicha**: tizim nginx/proksi ortida ishlaydi,
shuning uchun barcha so'rovlar bitta IP'dan kelib ko'rinadi. IP bo'yicha blok
bitta hujumchi tufayli **butun tashkilotni** kirishdan to'xtatib qo'yardi.
Login (username) bo'yicha blok esa faqat hujum qilinayotgan hisobni himoya
qiladi, boshqalar bemalol ishlaydi.

Yon ta'sir (qabul qilingan): hujumchi boshqa odamning loginini ataylab bloklab
qo'yishi mumkin (DoS). Shuning uchun chegara **qattiq emas** — 10/min va
50/soat, ya'ni haqiqiy foydalanuvchi parolni bir necha marta xato kiritsa ham
bloklanmaydi, lekin avtomatik tanlash amalda imkonsiz bo'ladi.

OGOHLANTIRISH: hisob joriy `CACHES` (default — LocMemCache) da saqlanadi,
ya'ni **har bir ishchi jarayon uchun alohida**. Bir nechta worker bilan
ishlaganda chegara shuncha marta yumshaydi. To'liq himoya uchun Redis
(`django.core.cache.backends.redis.RedisCache`) sozlanishi kerak.
"""
from rest_framework.throttling import SimpleRateThrottle


class _LoginThrottleBase(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        # `request.data` POST tanasidan keladi; login bo'lmasa (noto'g'ri
        # so'rov) throttle qo'llanilmaydi — baribir 400 qaytadi.
        username = request.data.get('username') if hasattr(request, 'data') else None
        if not username or not isinstance(username, str):
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': username.strip().lower(),
        }


class LoginRateThrottle(_LoginThrottleBase):
    """Qisqa oraliq — avtomatik tanlashni to'xtatadi."""
    scope = 'login'


class LoginHourThrottle(_LoginThrottleBase):
    """Uzoq oraliq — sekin, "past va sekin" tipidagi tanlashni to'xtatadi."""
    scope = 'login_hour'
