"""Group va Shift ga `external_code` (UUID) qo'shish — KPI integratsiyasi uchun.

UCH BOSQICHDA yoziladi, `makemigrations` avtomatik yozganidek bir bosqichda
EMAS. Sabab: `unique=True` maydonni mavjud qatorlari bor jadvalga qo'shganda
Django bitta default qiymatni HAMMA qatorga yozadi — natijada unikallik
buziladi va migratsiya `IntegrityError` bilan yiqiladi.

    1) maydon `null=True`, unikalliksiz qo'shiladi
    2) har bir qatorga ALOHIDA UUID yoziladi (RunPython)
    3) maydon `unique=True, null=False` ga o'tkaziladi

`reverse` — maydonni oddiy o'chirish, ma'lumot yo'qoladi (bu kutilgan holat:
maydon o'zi integratsiya uchun, orqaga qaytarilsa integratsiya ham to'xtaydi).
"""
import uuid

from django.db import migrations, models


def fill_codes(apps, schema_editor):
    for label in ('Group', 'Shift'):
        model = apps.get_model('academic', label)
        # `iterator()` — katta jadvalda hammasini xotiraga yig'masin
        for obj in model.objects.filter(external_code__isnull=True).iterator():
            model.objects.filter(pk=obj.pk).update(external_code=uuid.uuid4())


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('academic', '0013_curriculum_delivery_mode_group_delivery_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='group',
            name='external_code',
            field=models.UUIDField(null=True, editable=False, db_index=True,
                                   verbose_name='Tashqi kod (integratsiya)'),
        ),
        migrations.AddField(
            model_name='shift',
            name='external_code',
            field=models.UUIDField(null=True, editable=False, db_index=True,
                                   verbose_name='Tashqi kod (integratsiya)'),
        ),
        migrations.RunPython(fill_codes, noop),
        migrations.AlterField(
            model_name='group',
            name='external_code',
            field=models.UUIDField(default=uuid.uuid4, editable=False,
                                   unique=True, db_index=True,
                                   verbose_name='Tashqi kod (integratsiya)'),
        ),
        migrations.AlterField(
            model_name='shift',
            name='external_code',
            field=models.UUIDField(default=uuid.uuid4, editable=False,
                                   unique=True, db_index=True,
                                   verbose_name='Tashqi kod (integratsiya)'),
        ),
    ]
