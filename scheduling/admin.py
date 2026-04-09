from django.contrib import admin
from .models import (Teacher, TeacherBusyTime, TeacherSubjectAssignment,
                     TeacherMonthlyLoad, Schedule, ScheduleEntry,
                     Substitution, AuditLog,
                     LoadSheet, TeacherLoad, LoadDistribution)


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


# ─────────────────────────────────────────────
#  TAQSIMOT ADMIN
# ─────────────────────────────────────────────

class LoadDistributionInline(admin.TabularInline):
    model         = LoadDistribution
    extra         = 0
    readonly_fields = ['module_name', 'group_name', 'hours', 'curriculum_subject', 'group']
    can_delete    = False


class TeacherLoadInline(admin.TabularInline):
    model         = TeacherLoad
    extra         = 0
    readonly_fields = ['full_name', 'position', 'stavka', 'total_hours', 'teacher']
    can_delete    = False
    show_change_link = True


@admin.register(LoadSheet)
class LoadSheetAdmin(admin.ModelAdmin):
    list_display    = ['department', 'month', 'year', 'uploaded_by',
                       'uploaded_at', 'get_teachers_count', 'get_total_hours']
    list_filter     = ['year', 'month', 'department']
    readonly_fields = ['uploaded_by', 'uploaded_at']
    inlines         = [TeacherLoadInline]

    def get_teachers_count(self, obj):
        return obj.teacher_loads.exclude(
            stavka=TeacherLoad.Stavka.VACANT
        ).count()
    get_teachers_count.short_description = "O'qituvchilar"

    def get_total_hours(self, obj):
        return sum(t.total_hours for t in obj.teacher_loads.all())
    get_total_hours.short_description = "Jami soat"


@admin.register(TeacherLoad)
class TeacherLoadAdmin(admin.ModelAdmin):
    list_display    = ['full_name', 'position', 'stavka', 'total_hours',
                       'teacher', 'load_sheet']
    list_filter     = ['stavka', 'load_sheet__month', 'load_sheet__year',
                       'load_sheet__department']
    search_fields   = ['full_name']
    readonly_fields = ['teacher']
    inlines         = [LoadDistributionInline]


@admin.register(LoadDistribution)
class LoadDistributionAdmin(admin.ModelAdmin):
    list_display  = ['teacher_load', 'module_name', 'group_name', 'hours',
                     'curriculum_subject', 'group']
    list_filter   = ['teacher_load__load_sheet__month',
                     'teacher_load__load_sheet__year',
                     'teacher_load__load_sheet__department']
    search_fields = ['module_name', 'group_name', 'teacher_load__full_name']
