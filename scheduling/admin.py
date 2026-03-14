from django.contrib import admin
from .models import (Teacher, TeacherBusyTime, TeacherSubjectAssignment,
                     TeacherMonthlyLoad, Schedule, ScheduleEntry,
                     Substitution, AuditLog)


class TeacherBusyTimeInline(admin.TabularInline):
    model = TeacherBusyTime
    extra = 1


class TeacherSubjectAssignmentInline(admin.TabularInline):
    model = TeacherSubjectAssignment
    extra = 1


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display  = ['user', 'organization', 'personal_room', 'is_active']
    list_filter   = ['organization', 'is_active']
    inlines       = [TeacherBusyTimeInline, TeacherSubjectAssignmentInline]


@admin.register(TeacherBusyTime)
class TeacherBusyTimeAdmin(admin.ModelAdmin):
    list_display = ['teacher', 'date', 'start_time', 'end_time', 'reason']
    list_filter  = ['date', 'teacher']
    ordering     = ['date', 'start_time']


@admin.register(TeacherSubjectAssignment)
class TeacherSubjectAssignmentAdmin(admin.ModelAdmin):
    list_display  = ['teacher', 'major']
    filter_horizontal = ['subjects']


@admin.register(TeacherMonthlyLoad)
class TeacherMonthlyLoadAdmin(admin.ModelAdmin):
    list_display  = ['teacher', 'major', 'month', 'year', 'total_hours', 'status']
    list_filter   = ['status', 'year', 'month']
    list_editable = ['status']


class ScheduleEntryInline(admin.TabularInline):
    model = ScheduleEntry
    extra = 0
    readonly_fields = ['date', 'para', 'room', 'building',
                       'teacher', 'group', 'subject', 'lesson_type']


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ['title', 'organization', 'month', 'year',
                    'date_from', 'date_to', 'status']
    list_filter  = ['organization', 'status', 'year']
    inlines      = [ScheduleEntryInline]


@admin.register(ScheduleEntry)
class ScheduleEntryAdmin(admin.ModelAdmin):
    list_display = ['date', 'group', 'subject', 'lesson_type',
                    'teacher', 'para', 'room', 'building']
    list_filter  = ['date', 'lesson_type']
    ordering     = ['date', 'para__order']


@admin.register(Substitution)
class SubstitutionAdmin(admin.ModelAdmin):
    list_display = ['schedule_entry', 'original_teacher',
                    'substitute_teacher', 'status']
    list_filter  = ['status']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display    = ['timestamp', 'user', 'action', 'model_name', 'object_id']
    list_filter     = ['action', 'model_name']
    readonly_fields = ['timestamp', 'user', 'action', 'model_name',
                       'object_id', 'object_repr', 'changes']
    ordering        = ['-timestamp']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
