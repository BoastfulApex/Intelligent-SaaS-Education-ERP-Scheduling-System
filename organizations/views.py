from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Organization, Building, Room, Department, Position
from .serializers import (OrganizationSerializer, BuildingSerializer, RoomSerializer,
                           DepartmentSerializer, PositionSerializer)
from accounts.models import User
from permissions import IsSuperAdmin, IsOrgAdmin, IsOrgAdminOrReadOnly, IsEduAdminOrReadOnly


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.SUPER_ADMIN:
            return Organization.objects.all()
        return Organization.objects.filter(id=user.organization_id)


class BuildingViewSet(viewsets.ModelViewSet):
    serializer_class = BuildingSerializer
    permission_classes = [IsEduAdminOrReadOnly]

    def get_queryset(self):
        return Building.objects.filter(
            organization=self.request.user.organization
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class RoomViewSet(viewsets.ModelViewSet):
    serializer_class = RoomSerializer
    permission_classes = [IsEduAdminOrReadOnly]

    def get_queryset(self):
        return Room.objects.filter(
            building__organization=self.request.user.organization
        )


class DepartmentViewSet(viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    permission_classes = [IsOrgAdminOrReadOnly]

    def get_queryset(self):
        return Department.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class PositionViewSet(viewsets.ModelViewSet):
    # Lavozimlar ro'yxatini FAQAT org_admin(+) boshqaradi (yaratish/tahrirlash/
    # o'chirish); kafedra mudiri va boshqa autentifikatsiyalangan foydalanuvchilar
    # esa faqat o'qiydi — o'qituvchi profilida shu ro'yxatdan tanlash uchun.
    serializer_class = PositionSerializer
    permission_classes = [IsOrgAdminOrReadOnly]

    def get_queryset(self):
        return Position.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)