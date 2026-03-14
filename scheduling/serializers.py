from rest_framework import serializers
from .models import (Teacher, TeacherBusyTime, TeacherSubjectAssignment,
                     TeacherMonthlyLoad, Schedule, ScheduleEntry,
                     Substitution, AuditLog)


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
                  'start_time', 'end_time', 'reason']
        read_only_fields = ['id']

    def validate(self, data):
        if data['start_time'] >= data['end_time']:
            raise serializers.ValidationError(
                "Boshlanish vaqti tugash vaqtidan oldin bo'lishi kerak!"
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