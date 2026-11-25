from rest_framework import serializers
from .models import User


class RoleGuardMixin:
    """
    Rol eskalatsiyasidan himoya — **yaratishda HAM, tahrirlashda HAM**.

    HAQIQIY ZAIFLIK (2026-11-25, o'lchangan): avval `validate_role` faqat
    `UserCreateSerializer` da edi, `UserViewSet.get_serializer_class()` esa
    uni FAQAT `action == 'create'` uchun qaytarardi. Natijada `org_admin`:
      1) oddiy `teacher` yaratardi (bu ruxsat etilgan),
      2) so'ng o'sha foydalanuvchini `PATCH /users/{id}/ {"role":"super_admin"}`
         bilan ko'tarib yuborardi — hech qanday tekshiruvsiz (200 qaytardi).
    Hosil bo'lgan `super_admin` esa BARCHA tashkilotlar ma'lumotini ko'radi
    (`get_queryset()` larda super_admin uchun maxsus shart bor), ya'ni
    ko'p-tashkilotli ajratish butunlay buzilardi.
    """

    def validate_role(self, value):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return value
        # Faqat super_admin super_admin tayinlay oladi (org_admin ham, boshqa
        # rollar ham emas) — ataylab rolga emas, "super_admin EMAS" shartiga
        # bog'langan, yangi rol qo'shilsa ham himoya saqlanadi.
        if (request.user.role != User.Role.SUPER_ADMIN
                and value == User.Role.SUPER_ADMIN):
            raise serializers.ValidationError(
                "Super_admin rolini faqat super_admin bera oladi!"
            )
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        # Mavjud super_admin hisobini quyi rolli foydalanuvchi tahrirlay
        # olmasligi kerak (aks holda uni o'chirib/pasaytirib qo'yishi mumkin).
        if (request and request.user.is_authenticated and self.instance
                and getattr(self.instance, 'role', None) == User.Role.SUPER_ADMIN
                and request.user.role != User.Role.SUPER_ADMIN):
            raise serializers.ValidationError(
                "Super_admin hisobini faqat super_admin tahrirlashi mumkin."
            )
        return attrs


class UserSerializer(RoleGuardMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name',
                  'email', 'role', 'organization', 'phone', 'is_active']
        read_only_fields = ['id']


class UserCreateSerializer(RoleGuardMixin, serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'role', 'organization', 'phone', 'password']
        extra_kwargs = {
            # organization ViewSet.perform_create da o'rnatiladi,
            # shuning uchun majburiy emas
            'organization': {'required': False},
        }

    # `validate_role` / `validate` — `RoleGuardMixin` da (yaratish va
    # tahrirlash uchun BIR XIL qoida).

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)