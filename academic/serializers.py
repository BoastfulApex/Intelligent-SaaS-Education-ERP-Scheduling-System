from rest_framework import serializers
from .models import (Major, Subject, Curriculum, CurriculumBlock,
                     CurriculumSubject, Group, Shift, Para, GroupAssignment)


class MajorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Major
        fields = ['id', 'organization', 'name', 'code', 'is_active']
        read_only_fields = ['id', 'organization']


class SubjectSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)

    class Meta:
        model = Subject
        fields = ['id', 'organization', 'name', 'code',
                  'department', 'department_name']
        read_only_fields = ['id', 'organization']


class CurriculumSubjectSerializer(serializers.ModelSerializer):
    subject_name      = serializers.CharField(source='subject.name', read_only=True)
    subject_code      = serializers.CharField(source='subject.code', read_only=True)
    department_name   = serializers.CharField(source='department.name', read_only=True)
    auditorium_hours  = serializers.IntegerField(read_only=True)
    grand_total_hours = serializers.IntegerField(read_only=True)
    total_paras       = serializers.IntegerField(read_only=True)
    weekly_total      = serializers.IntegerField(read_only=True)

    class Meta:
        model = CurriculumSubject
        fields = [
            'id', 'block', 'subject', 'subject_name', 'subject_code',
            'department', 'department_name',
            'order',
            'lecture_hours', 'practice_hours', 'field_hours', 'independent_hours',
            'auditorium_hours', 'grand_total_hours', 'total_paras',
            'week1_hours', 'week2_hours', 'week3_hours', 'week4_hours', 'weekly_total',
        ]
        read_only_fields = ['id', 'auditorium_hours', 'grand_total_hours', 'total_paras', 'weekly_total']


class CurriculumBlockSerializer(serializers.ModelSerializer):
    subjects          = CurriculumSubjectSerializer(many=True, read_only=True)
    total_hours       = serializers.IntegerField(read_only=True)
    lecture_hours     = serializers.IntegerField(read_only=True)
    practice_hours    = serializers.IntegerField(read_only=True)
    field_hours       = serializers.IntegerField(read_only=True)
    independent_hours = serializers.IntegerField(read_only=True)
    total_paras       = serializers.IntegerField(read_only=True)

    class Meta:
        model = CurriculumBlock
        fields = [
            'id', 'curriculum', 'order', 'name',
            'subjects',
            'total_hours', 'lecture_hours', 'practice_hours',
            'field_hours', 'independent_hours', 'total_paras',
        ]
        read_only_fields = ['id', 'total_hours', 'lecture_hours', 'practice_hours',
                            'field_hours', 'independent_hours', 'total_paras']


class CurriculumSerializer(serializers.ModelSerializer):
    major_name         = serializers.CharField(source='major.name', read_only=True)
    status_display     = serializers.CharField(source='get_status_display', read_only=True)
    study_form_display = serializers.CharField(source='get_study_form_display', read_only=True)
    blocks             = CurriculumBlockSerializer(many=True, read_only=True)

    class Meta:
        model = Curriculum
        fields = [
            'id', 'major', 'major_name', 'name',
            'contingent', 'study_form', 'study_form_display',
            'duration_weeks', 'total_hours',
            'status', 'status_display',
            'blocks',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class GroupSerializer(serializers.ModelSerializer):
    major_name    = serializers.CharField(source='major.name', read_only=True)
    month_display = serializers.CharField(source='get_month_display', read_only=True)

    class Meta:
        model = Group
        fields = ['id', 'organization', 'major', 'major_name',
                  'name', 'student_count', 'month', 'month_display',
                  'year', 'start_date', 'end_date', 'is_active']
        read_only_fields = ['id', 'organization']


class ParaSerializer(serializers.ModelSerializer):
    shift_name     = serializers.CharField(source='shift.name', read_only=True)
    duration_hours = serializers.SerializerMethodField()

    class Meta:
        model = Para
        fields = ['id', 'shift', 'shift_name', 'name', 'order',
                  'start_time', 'end_time', 'duration_hours', 'is_active']
        read_only_fields = ['id', 'duration_hours']

    def get_duration_hours(self, obj):
        start    = obj.start_time
        end      = obj.end_time
        duration = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        return round(duration / 60, 1)


class ShiftSerializer(serializers.ModelSerializer):
    paras       = ParaSerializer(many=True, read_only=True)
    total_paras = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = ['id', 'organization', 'name', 'start_time',
                  'end_time', 'is_active', 'paras', 'total_paras']
        read_only_fields = ['id', 'organization']

    def get_total_paras(self, obj):
        return obj.paras.filter(is_active=True).count()


class GroupAssignmentSerializer(serializers.ModelSerializer):
    group_name    = serializers.CharField(source='group.name', read_only=True)
    shift_name    = serializers.CharField(source='shift.name', read_only=True)
    building_name = serializers.CharField(source='building.name', read_only=True)
    month_display = serializers.SerializerMethodField()

    class Meta:
        model = GroupAssignment
        fields = ['id', 'group', 'group_name', 'shift', 'shift_name',
                  'building', 'building_name', 'month', 'month_display', 'year']
        read_only_fields = ['id']

    def get_month_display(self, obj):
        months = {
            1: 'Yanvar',  2: 'Fevral',  3: 'Mart',
            4: 'Aprel',   5: 'May',     6: 'Iyun',
            7: 'Iyul',    8: 'Avgust',  9: 'Sentabr',
            10: 'Oktabr', 11: 'Noyabr', 12: 'Dekabr'
        }
        return months.get(obj.month, '')

    def validate(self, data):
        exists = GroupAssignment.objects.filter(
            group=data['group'],
            month=data['month'],
            year=data['year']
        ).exclude(pk=self.instance.pk if self.instance else None).exists()
        if exists:
            raise serializers.ValidationError(
                "Bu guruh uchun bu oyda allaqachon smena va bino biriktirilgan!"
            )
        return data