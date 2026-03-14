from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import (Major, Subject, Curriculum, CurriculumBlock,
                     CurriculumSubject, Group, Shift, Para, GroupAssignment)
from .serializers import (MajorSerializer, SubjectSerializer,
                           CurriculumSerializer, CurriculumBlockSerializer,
                           CurriculumSubjectSerializer, GroupSerializer,
                           ShiftSerializer, ParaSerializer,
                           GroupAssignmentSerializer)


class MajorViewSet(viewsets.ModelViewSet):
    serializer_class = MajorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Major.objects.filter(
            organization=self.request.user.organization
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class SubjectViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Subject.objects.filter(
            organization=self.request.user.organization
        )
                
    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        """Bir vaqtda ko'p fan yaratish"""
        subjects = request.data.get('subjects', [])
        if not subjects:
            return Response(
                {'error': 'subjects maydoni bo\'sh!'},
                status=status.HTTP_400_BAD_REQUEST
            )

        created = []
        errors  = []

        for item in subjects:
            try:
                subject, _ = Subject.objects.get_or_create(
                    organization=request.user.organization,
                    code=item['code'],
                    defaults={
                        'name': item['name'],
                        'department_id': item.get('department')  # None bo'lsa ham ishlaydi
                    }
                )
                created.append(subject)
            except Exception as e:
                errors.append({'code': item.get('code'), 'error': str(e)})

        return Response({
            'created': SubjectSerializer(created, many=True).data,
            'errors': errors
        }, status=status.HTTP_201_CREATED)
    
    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class CurriculumViewSet(viewsets.ModelViewSet):
    serializer_class = CurriculumSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Curriculum.objects.filter(
            major__organization=self.request.user.organization
        ).prefetch_related('blocks__subjects')

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        curriculum = self.get_object()
        if curriculum.status == Curriculum.Status.ARCHIVED:
            return Response(
                {'error': 'Bu o\'quv reja allaqachon arxivlangan!'},
                status=status.HTTP_400_BAD_REQUEST
            )
        curriculum.archive()
        return Response({'message': 'O\'quv reja arxivlandi'})


class CurriculumBlockViewSet(viewsets.ModelViewSet):
    serializer_class = CurriculumBlockSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CurriculumBlock.objects.filter(
            curriculum__major__organization=self.request.user.organization
        ).select_related('department', 'curriculum').prefetch_related('subjects')


class CurriculumSubjectViewSet(viewsets.ModelViewSet):
    serializer_class = CurriculumSubjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CurriculumSubject.objects.filter(
            block__curriculum__major__organization=self.request.user.organization
        ).select_related('subject', 'block')


class GroupViewSet(viewsets.ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Group.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ShiftViewSet(viewsets.ModelViewSet):
    serializer_class = ShiftSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Shift.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        ).prefetch_related('paras')

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ParaViewSet(viewsets.ModelViewSet):
    serializer_class = ParaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Para.objects.filter(
            shift__organization=self.request.user.organization,
            is_active=True
        ).select_related('shift')


class GroupAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = GroupAssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return GroupAssignment.objects.filter(
            group__organization=self.request.user.organization
        ).select_related('group', 'shift', 'building')