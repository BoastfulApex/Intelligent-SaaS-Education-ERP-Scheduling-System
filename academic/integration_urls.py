"""KPI integratsiyasi endpointlari — `/api/v1/integration/...`

Alohida fayl: `academic/urls.py` router asosida qurilgan (ViewSet'lar), bular
esa oddiy `APIView`. Aralashtirilsa router konfiguratsiyasi chalkashadi.
"""
from django.urls import path

from .integration_views import (
    IntegrationBuildingsAPIView,
    IntegrationDayAssignmentsAPIView,
    IntegrationGroupsAPIView,
)

urlpatterns = [
    path('integration/groups/', IntegrationGroupsAPIView.as_view(),
         name='integration-groups'),
    path('integration/buildings/', IntegrationBuildingsAPIView.as_view(),
         name='integration-buildings'),
    path('integration/day-assignments/',
         IntegrationDayAssignmentsAPIView.as_view(),
         name='integration-day-assignments'),
]
