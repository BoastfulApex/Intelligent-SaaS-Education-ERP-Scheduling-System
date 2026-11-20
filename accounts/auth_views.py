"""
Autentifikatsiya view'lari — login (brute force himoyasi bilan) va logout
(refresh tokenni bekor qilish).

Avval `config/urls.py` to'g'ridan-to'g'ri SimpleJWT'ning standart
`TokenObtainPairView` ini ishlatardi — unda hech qanday tezlik chegarasi
yo'q edi (o'lchangan: 12 ta ketma-ket noto'g'ri parol → 12 ta 401, lockout
yo'q). Logout esa umuman mavjud emasdi: "Chiqish" faqat klient tomonida
localStorage'ni tozalardi, refresh token 7 kun amal qilaverardi.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .throttling import LoginHourThrottle, LoginRateThrottle


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Standart login + login bo'yicha (IP emas) tezlik chegarasi."""
    throttle_classes = [LoginRateThrottle, LoginHourThrottle]


class LogoutView(APIView):
    """
    POST /api/auth/logout/  { "refresh": "<token>" }

    Refresh tokenni blacklist'ga qo'shadi — shundan keyin u bilan yangi
    access token olib bo'lmaydi. Access token esa o'z muddati (8 soat)
    tugaguncha amal qiladi: JWT stateless, uni serverdan "o'chirib"
    bo'lmaydi.

    Har doim **205** qaytaradi (token yaroqsiz bo'lsa ham) — klient uchun
    "chiqish bajarildi" degani, va mavjud/yaroqsiz tokenni farqlab, token
    sanashga imkon bermaslik uchun.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get('refresh')
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                # Muddati o'tgan yoki allaqachon bekor qilingan — xato emas.
                pass
        return Response(status=status.HTTP_205_RESET_CONTENT)
