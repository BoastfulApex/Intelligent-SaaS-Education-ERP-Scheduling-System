from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
)

from accounts.auth_views import LogoutView, ThrottledTokenObtainPairView

# Admin manzili `.env` dagi `ADMIN_URL` orqali o'zgartiriladi (standart
# `admin/` — topish oson va brute force uchun ochiq nishon). Bo'sh qiymat
# berilsa, admin umuman ulanmaydi.
ADMIN_URL = getattr(settings, 'ADMIN_URL', 'admin/')

urlpatterns = []
if ADMIN_URL:
    urlpatterns.append(path(ADMIN_URL, admin.site.urls))

urlpatterns += [
    # JWT Auth — login'da brute force himoyasi bor (accounts/throttling.py)
    path('api/auth/login/', ThrottledTokenObtainPairView.as_view(), name='login'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),

    # Apps
    path('api/v1/', include('accounts.urls')),
    path('api/v1/', include('organizations.urls')),
    path('api/v1/', include('academic.urls')),
    path('api/v1/', include('scheduling.urls')),
    path('api/v1/', include('reports.urls')),
    # KPI (EEMSportedu) integratsiyasi — API kalit bilan, JWT emas
    path('api/v1/', include('academic.integration_urls')),

    # API Dokumentatsiya
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]