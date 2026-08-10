import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0013_lessonjournal'),
    ]

    operations = [
        migrations.CreateModel(
            name='LessonAttendance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('kpi_student_id', models.PositiveIntegerField(
                    verbose_name='KPI tinglovchi ID')),
                ('full_name', models.CharField(max_length=255,
                                               verbose_name="F.I.Sh.")),
                ('checked_in_kpi', models.BooleanField(
                    default=False, verbose_name="KPI'da qayd (xom fakt)")),
                ('check_in_time', models.TimeField(blank=True, null=True)),
                ('marked_present', models.BooleanField(
                    default=False, verbose_name="O'qituvchi tasdiqlagan")),
                ('marked_at', models.DateTimeField(blank=True, null=True)),
                ('journal', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attendance_records',
                    to='scheduling.lessonjournal', verbose_name='Dars jurnali')),
            ],
            options={
                'verbose_name': 'Davomat',
                'verbose_name_plural': 'Davomat',
                'db_table': 'lesson_attendance',
                'unique_together': {('journal', 'kpi_student_id')},
            },
        ),
    ]
