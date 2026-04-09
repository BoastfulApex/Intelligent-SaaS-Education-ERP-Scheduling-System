from django.contrib import admin
from .models import Major, Subject, Curriculum, CurriculumBlock, CurriculumSubject, Group, Shift, Para, GroupAssignment


@admin.register(Major)
class MajorAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'organization', 'is_active']
    list_filter  = ['organization', 'is_active']


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'organization']
    list_filter  = ['organization']


class CurriculumSubjectInline(admin.TabularInline):
    model  = CurriculumSubject
    extra  = 1
    fields = [
        'order', 'subject',
        'lecture_hours', 'practice_hours', 'field_hours', 'independent_hours',
        'week1_hours', 'week2_hours', 'week3_hours', 'week4_hours',
    ]


class CurriculumBlockInline(admin.TabularInline):
    model  = CurriculumBlock
    extra  = 1
    fields = ['order', 'name']


@admin.register(Curriculum)
class CurriculumAdmin(admin.ModelAdmin):
    list_display  = ['name', 'major', 'contingent', 'duration_weeks', 'total_hours', 'study_form', 'status', 'created_at']
    list_filter   = ['status', 'study_form', 'major']
    search_fields = ['name', 'contingent']
    inlines       = [CurriculumBlockInline]


@admin.register(CurriculumBlock)
class CurriculumBlockAdmin(admin.ModelAdmin):
    list_display = ['curriculum', 'order', 'name', 'total_hours',
                    'lecture_hours', 'practice_hours', 'field_hours', 'independent_hours']
    list_filter  = ['curriculum']
    ordering     = ['curriculum', 'order']
    inlines      = [CurriculumSubjectInline]

    def total_hours(self, obj):      return obj.total_hours
    def lecture_hours(self, obj):    return obj.lecture_hours
    def practice_hours(self, obj):   return obj.practice_hours
    def field_hours(self, obj):      return obj.field_hours
    def independent_hours(self, obj):return obj.independent_hours

    total_hours.short_description       = "Jami"
    lecture_hours.short_description     = "Nazariy"
    practice_hours.short_description    = "Amaliy"
    field_hours.short_description       = "Ko'chma"
    independent_hours.short_description = "Mustaqil"


@admin.register(CurriculumSubject)
class CurriculumSubjectAdmin(admin.ModelAdmin):
    list_display  = [
        'subject', 'block', 'order',
        'lecture_hours', 'practice_hours', 'field_hours', 'independent_hours',
        'get_auditorium_hours', 'get_grand_total',
        'week1_hours', 'week2_hours', 'week3_hours', 'week4_hours',
    ]
    list_filter   = ['block__curriculum']
    search_fields = ['subject__name']
    ordering      = ['block__order', 'order']

    def get_auditorium_hours(self, obj):
        return obj.auditorium_hours
    get_auditorium_hours.short_description = "Auditoriya"

    def get_grand_total(self, obj):
        return obj.grand_total_hours
    get_grand_total.short_description = "Jami"


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'major', 'student_count', 'year', 'is_active']
    list_filter  = ['organization', 'is_active', 'year']


class ParaInline(admin.TabularInline):
    model = Para
    extra = 1
    ordering = ['order']


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'start_time', 'end_time', 'is_active']
    list_filter  = ['organization', 'is_active']
    inlines      = [ParaInline]


@admin.register(Para)
class ParaAdmin(admin.ModelAdmin):
    list_display = ['name', 'shift', 'order', 'start_time', 'end_time']
    list_filter  = ['shift']
    ordering     = ['shift', 'order']


@admin.register(GroupAssignment)
class GroupAssignmentAdmin(admin.ModelAdmin):
    list_display = ['group', 'shift', 'building', 'month', 'year']
    list_filter  = ['year', 'month']
