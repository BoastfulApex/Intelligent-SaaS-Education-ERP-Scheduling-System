from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrganizationViewSet, BuildingViewSet, RoomViewSet, DepartmentViewSet, PositionViewSet

router = DefaultRouter()
router.register(r'organizations', OrganizationViewSet, basename='organization')
router.register(r'buildings', BuildingViewSet, basename='building')
router.register(r'rooms', RoomViewSet, basename='room')
router.register(r'departments', DepartmentViewSet, basename='department')
router.register(r'positions', PositionViewSet, basename='position')

urlpatterns = [
    path('', include(router.urls)),
]