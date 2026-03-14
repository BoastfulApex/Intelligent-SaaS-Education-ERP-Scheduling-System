from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN        = 'super_admin',  'System Super Admin'
        ORG_ADMIN          = 'org_admin',    'Organization Admin'
        EDU_ADMIN          = 'edu_admin',    "O'quv Bo'limi Admini"
        DEPARTMENT_MANAGER = 'dept_manager', 'Kafedra Mudiri'
        TEACHER            = 'teacher',      "O'qituvchi"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.TEACHER
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = 'users'
        verbose_name = "Foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"