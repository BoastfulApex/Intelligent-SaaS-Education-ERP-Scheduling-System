from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (TeacherViewSet, TeacherBusyTimeViewSet,
                    TeacherSubjectAssignmentViewSet, TeacherMonthlyLoadViewSet,
                    ScheduleViewSet, ScheduleEntryViewSet,
                    SubstitutionViewSet, AuditLogViewSet,
                    LoadSheetViewSet)

router = DefaultRouter()
router.register(r'teachers', TeacherViewSet, basename='teacher')
router.register(r'teacher-busy-times', TeacherBusyTimeViewSet, basename='teacher-busy-time')
router.register(r'teacher-subject-assignments', TeacherSubjectAssignmentViewSet, basename='teacher-subject-assignment')
router.register(r'teacher-monthly-loads', TeacherMonthlyLoadViewSet, basename='teacher-monthly-load')
router.register(r'schedules', ScheduleViewSet, basename='schedule')
router.register(r'schedule-entries', ScheduleEntryViewSet, basename='schedule-entry')
router.register(r'substitutions', SubstitutionViewSet, basename='substitution')
router.register(r'audit-logs', AuditLogViewSet, basename='auditlog')
router.register(r'load-sheets', LoadSheetViewSet, basename='load-sheet')

urlpatterns = [
    path('', include(router.urls)),
]