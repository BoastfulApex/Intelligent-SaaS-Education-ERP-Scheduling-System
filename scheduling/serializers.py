from rest_framework import serializers
from .models import (Teacher, TeacherBusyTime, TeacherSubjectAssignment,
                     TeacherMonthlyLoad, Schedule, ScheduleEntry,
                     Substitution, AuditLog,
                     LoadSheet, TeacherLoad, LoadDistribution)


class TeacherSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = Teacher
        fields = ['id', 'user', 'full_name', 'organization',
                  'subjects', 'personal_room', 'is_active']
        read_only_fields = ['id', 'organization']


class TeacherBusyTimeSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.user.get_full_name', read_only=True)

    class Meta:
        model = TeacherBusyTime
        fields = ['id', 'teacher', 'teacher_name', 'date',
                  'is_all_day', 'start_time', 'end_time', 'reason']
        read_only_fields = ['id']

    def validate(self, data):
        is_all_day  = data.get('is_all_day', False)
        start_time  = data.get('start_time')
        end_time    = data.get('end_time')

        # Butun kun emas bo'lsa — vaqtlar majburiy
        if not is_all_day:
            if not start_time or not end_time:
                raise serializers.ValidationError(
                    "is_all_day=False bo'lganda start_time va end_time majburiy!"
                )
            if start_time >= end_time:
                raise serializers.ValidationError(
                    "Boshlanish vaqti tugash vaqtidan oldin bo'lishi kerak!"
                )

        # Bir xil sana + o'qituvchi uchun qoplanish tekshiruvi
        teacher = data.get('teacher')
        date    = data.get('date')
        instance_id = self.instance.id if self.instance else None

        if teacher and date:
            existing = TeacherBusyTime.objects.filter(
                teacher=teacher, date=date
            ).exclude(pk=instance_id)

            for bt in existing:
                # Yangi yozuv ham, mavjud ham butun kun → conflict
                if is_all_day or bt.is_all_day:
                    raise serializers.ValidationError(
                        f"{date} kuni uchun allaqachon band vaqt mavjud!"
                    )
                # Ikki oraliq qoplanadimi?
                if start_time and end_time and bt.start_time and bt.end_time:
                    if start_time < bt.end_time and end_time > bt.start_time:
                        raise serializers.ValidationError(
                            f"{date} kuni {bt.start_time.strftime('%H:%M')}-"
                            f"{bt.end_time.strftime('%H:%M')} bilan qoplanish bor!"
                        )
        return data


class TeacherSubjectAssignmentSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.user.get_full_name', read_only=True)
    major_name   = serializers.CharField(source='major.name', read_only=True)

    class Meta:
        model = TeacherSubjectAssignment
        fields = ['id', 'teacher', 'teacher_name', 'major',
                  'major_name', 'subjects']
        read_only_fields = ['id']


class TeacherMonthlyLoadSerializer(serializers.ModelSerializer):
    teacher_name   = serializers.CharField(source='teacher.user.get_full_name', read_only=True)
    major_name     = serializers.CharField(source='major.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_paras    = serializers.IntegerField(read_only=True)
    month_display  = serializers.SerializerMethodField()

    class Meta:
        model = TeacherMonthlyLoad
        fields = ['id', 'teacher', 'teacher_name', 'major', 'major_name',
                  'month', 'month_display', 'year', 'total_hours',
                  'total_paras', 'status', 'status_display',
                  'assigned_by', 'created_at']
        read_only_fields = ['id', 'total_paras', 'created_at']

    def get_month_display(self, obj):
        months = {
            1: 'Yanvar',  2: 'Fevral',  3: 'Mart',
            4: 'Aprel',   5: 'May',     6: 'Iyun',
            7: 'Iyul',    8: 'Avgust',  9: 'Sentabr',
            10: 'Oktabr', 11: 'Noyabr', 12: 'Dekabr'
        }
        return months.get(obj.month, '')

    def validate(self, data):
        if data['total_hours'] % 2 != 0:
            raise serializers.ValidationError(
                "Soat juft son bo'lishi kerak (1 para = 2 soat)!"
            )
        return data


class ScheduleEntrySerializer(serializers.ModelSerializer):
    teacher_name    = serializers.CharField(source='teacher.user.get_full_name', read_only=True)
    group_name      = serializers.CharField(source='group.name', read_only=True)
    subject_name    = serializers.CharField(source='subject.name', read_only=True)
    room_name       = serializers.CharField(source='room.name', read_only=True)
    building_name   = serializers.CharField(source='building.name', read_only=True)
    para_name       = serializers.CharField(source='para.name', read_only=True)
    start_time      = serializers.TimeField(source='para.start_time', read_only=True)
    end_time        = serializers.TimeField(source='para.end_time', read_only=True)
    weekday_display = serializers.SerializerMethodField()
    lesson_type_display = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleEntry
        fields = ['id', 'schedule', 'teacher', 'teacher_name',
                  'group', 'group_name', 'subject', 'subject_name',
                  'lesson_type', 'lesson_type_display',
                  'room', 'room_name', 'building', 'building_name',
                  'para', 'para_name', 'start_time', 'end_time',
                  'date', 'weekday_display', 'is_substituted']
        read_only_fields = ['id']

    def get_weekday_display(self, obj):
        days = {
            1: 'Dushanba', 2: 'Seshanba', 3: 'Chorshanba',
            4: 'Payshanba', 5: 'Juma',    6: 'Shanba'
        }
        return days.get(obj.date.isoweekday(), '')

    def get_lesson_type_display(self, obj):
        return 'Nazariy' if obj.lesson_type == 'lecture' else 'Amaliy'


class ScheduleSerializer(serializers.ModelSerializer):
    entries        = ScheduleEntrySerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_entries  = serializers.SerializerMethodField()

    class Meta:
        model = Schedule
        fields = ['id', 'organization', 'title', 'month', 'year',
                  'date_from', 'date_to', 'status', 'status_display',
                  'generated_by', 'generated_at', 'total_entries', 'entries']
        read_only_fields = ['id', 'generated_at']

    def get_total_entries(self, obj):
        return obj.entries.count()


class SubstitutionSerializer(serializers.ModelSerializer):
    original_teacher_name   = serializers.CharField(
        source='original_teacher.user.get_full_name', read_only=True)
    substitute_teacher_name = serializers.CharField(
        source='substitute_teacher.user.get_full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Substitution
        fields = ['id', 'schedule_entry', 'original_teacher',
                  'original_teacher_name', 'substitute_teacher',
                  'substitute_teacher_name', 'date', 'reason',
                  'status', 'status_display', 'created_at']
        read_only_fields = ['id', 'created_at']


class AuditLogSerializer(serializers.ModelSerializer):
    user_name      = serializers.CharField(source='user.get_full_name', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'organization', 'user', 'user_name',
                  'action', 'action_display', 'model_name',
                  'object_id', 'object_repr', 'changes', 'timestamp']
        read_only_fields = fields


# ─────────────────────────────────────────────
#  TAQSIMOT SERIALIZERS
# ─────────────────────────────────────────────

class LoadDistributionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = LoadDistribution
        fields = ['id', 'module_name', 'group_name', 'hours',
                  'curriculum_subject', 'group']
        read_only_fields = fields


class TeacherLoadSerializer(serializers.ModelSerializer):
    distributions   = LoadDistributionSerializer(many=True, read_only=True)
    stavka_display  = serializers.CharField(source='get_stavka_display', read_only=True)

    class Meta:
        model  = TeacherLoad
        fields = ['id', 'full_name', 'position', 'stavka', 'stavka_display',
                  'total_hours', 'teacher', 'distributions']
        read_only_fields = fields


class LoadSheetSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)
    uploaded_by_name= serializers.CharField(source='uploaded_by.get_full_name', read_only=True)
    teacher_loads   = TeacherLoadSerializer(many=True, read_only=True)
    month_display   = serializers.SerializerMethodField()
    total_teachers  = serializers.SerializerMethodField()
    total_hours     = serializers.SerializerMethodField()

    class Meta:
        model  = LoadSheet
        fields = ['id', 'department', 'department_name', 'month', 'month_display',
                  'year', 'notes', 'uploaded_by', 'uploaded_by_name',
                  'uploaded_at', 'total_teachers', 'total_hours', 'teacher_loads']
        read_only_fields = fields

    def get_month_display(self, obj):
        months = {
            1: 'Yanvar',  2: 'Fevral',  3: 'Mart',
            4: 'Aprel',   5: 'May',     6: 'Iyun',
            7: 'Iyul',    8: 'Avgust',  9: 'Sentabr',
            10: 'Oktabr', 11: 'Noyabr', 12: 'Dekabr'
        }
        return months.get(obj.month, '')

    def get_total_teachers(self, obj):
        return obj.teacher_loads.exclude(stavka=TeacherLoad.Stavka.VACANT).count()

    def get_total_hours(self, obj):
        return sum(t.total_hours for t in obj.teacher_loads.all())