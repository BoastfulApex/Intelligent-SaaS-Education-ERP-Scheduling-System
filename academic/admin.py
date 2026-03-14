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
    model = CurriculumSubject
    extra = 1


class CurriculumBlockInline(admin.TabularInline):
    model = CurriculumBlock
    extra = 1


@admin.register(Curriculum)
class CurriculumAdmin(admin.ModelAdmin):
    list_display = ['name', 'major', 'status', 'created_at']
    list_filter  = ['status']
    inlines      = [CurriculumBlockInline]


@admin.register(CurriculumBlock)
class CurriculumBlockAdmin(admin.ModelAdmin):
    list_display = ['curriculum', 'order', 'department', 'total_hours', 'total_paras']
    list_filter  = ['curriculum']
    ordering     = ['curriculum', 'order']
    inlines      = [CurriculumSubjectInline]


@admin.register(CurriculumSubject)
class CurriculumSubjectAdmin(admin.ModelAdmin):
    list_display = ['block', 'subject', 'lesson_type', 'total_hours', 'total_paras']
    list_filter  = ['lesson_type']


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
