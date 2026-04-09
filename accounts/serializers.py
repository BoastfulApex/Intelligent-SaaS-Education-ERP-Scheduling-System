from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name',
                  'email', 'role', 'organization', 'phone', 'is_active']
        read_only_fields = ['id']


class UserCreateSerializer(serializers.ModelSerializer):
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

    def validate_role(self, value):
        """
        Rol eskalatsiyasini oldini olish:
          - super_admin → istalgan rol bera oladi
          - org_admin   → faqat o'z tashkiloti uchun, super_admin bera olmaydi
        """
        request = self.context.get('request')
        if not request:
            return value
        requester = request.user
        if (
            requester.role == User.Role.ORG_ADMIN
            and value == User.Role.SUPER_ADMIN
        ):
            raise serializers.ValidationError(
                "Org_admin super_admin roli bera olmaydi!"
            )
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)