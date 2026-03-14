from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (MajorViewSet, SubjectViewSet, CurriculumViewSet,
                    CurriculumBlockViewSet, CurriculumSubjectViewSet,
                    GroupViewSet, ShiftViewSet, ParaViewSet,
                    GroupAssignmentViewSet)

router = DefaultRouter()
router.register(r'majors', MajorViewSet, basename='major')
router.register(r'subjects', SubjectViewSet, basename='subject')
router.register(r'curriculums', CurriculumViewSet, basename='curriculum')
router.register(r'curriculum-blocks', CurriculumBlockViewSet, basename='curriculum-block')
router.register(r'curriculum-subjects', CurriculumSubjectViewSet, basename='curriculum-subject')
router.register(r'groups', GroupViewSet, basename='group')
router.register(r'shifts', ShiftViewSet, basename='shift')
router.register(r'paras', ParaViewSet, basename='para')
router.register(r'group-assignments', GroupAssignmentViewSet, basename='group-assignment')

urlpatterns = [path('', include(router.urls))]

