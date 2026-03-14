from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import User
from .serializers import UserSerializer, UserCreateSerializer, ChangePasswordSerializer
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['role', 'is_active']
    search_fields = ['username', 'first_name', 'last_name', 'email']
    
    
    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.SUPER_ADMIN:
            return User.objects.all()
        return User.objects.filter(organization=user.organization)

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        """Joriy foydalanuvchi ma'lumotlari"""
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=['post'], url_path='change-password')
    def change_password(self, request):
        """Parol o'zgartirish"""
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {'error': 'Eski parol noto\'g\'ri'},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        return Response({'message': 'Parol muvaffaqiyatli o\'zgartirildi'})