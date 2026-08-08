"""Building.external_code (UUID) + IntegrationClient modeli.

`external_code` uch bosqichda qo'shiladi — sababi `academic/0014` dagi
izohda batafsil (unique maydonni mavjud qatorlarga qo'shish muammosi).
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


def fill_codes(apps, schema_editor):
    Building = apps.get_model('organizations', 'Building')
    for obj in Building.objects.filter(external_code__isnull=True).iterator():
        Building.objects.filter(pk=obj.pk).update(external_code=uuid.uuid4())


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0006_position'),
    ]

    operations = [
        migrations.AddField(
            model_name='building',
            name='external_code',
            field=models.UUIDField(null=True, editable=False, db_index=True,
                                   verbose_name='Tashqi kod (integratsiya)'),
        ),
        migrations.RunPython(fill_codes, noop),
        migrations.AlterField(
            model_name='building',
            name='external_code',
            field=models.UUIDField(default=uuid.uuid4, editable=False,
                                   unique=True, db_index=True,
                                   verbose_name='Tashqi kod (integratsiya)'),
        ),
        migrations.CreateModel(
            name='IntegrationClient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='Nomi')),
                ('key_prefix', models.CharField(db_index=True, max_length=12,
                                                unique=True)),
                ('key_hash', models.CharField(max_length=64)),
                ('scopes', models.JSONField(blank=True, default=list)),
                ('is_active', models.BooleanField(default=True)),
                ('last_used', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='integration_clients',
                    to='organizations.organization')),
            ],
            options={
                'verbose_name': 'Integratsiya mijozi',
                'verbose_name_plural': 'Integratsiya mijozlari',
                'db_table': 'integration_clients',
            },
        ),
    ]
