from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
import datetime

from .models import (Teacher, TeacherBusyTime, TeacherSubjectAssignment,
                     TeacherMonthlyLoad, Schedule, ScheduleEntry,
                     Substitution, AuditLog)
from .serializers import (TeacherSerializer, TeacherBusyTimeSerializer,
                           TeacherSubjectAssignmentSerializer,
                           TeacherMonthlyLoadSerializer, ScheduleSerializer,
                           ScheduleEntrySerializer, SubstitutionSerializer,
                           AuditLogSerializer)
from academic.models import Para, GroupAssignment, Group, CurriculumSubject
from organizations.models import Room


class TeacherViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Teacher.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        ).select_related('user', 'personal_room')


class TeacherBusyTimeViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherBusyTimeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TeacherBusyTime.objects.filter(
            teacher__organization=self.request.user.organization
        ).select_related('teacher__user')


class TeacherSubjectAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherSubjectAssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TeacherSubjectAssignment.objects.filter(
            teacher__organization=self.request.user.organization
        ).select_related('teacher__user', 'major').prefetch_related('subjects')


class TeacherMonthlyLoadViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherMonthlyLoadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TeacherMonthlyLoad.objects.filter(
            teacher__organization=self.request.user.organization
        ).select_related('teacher__user', 'major')

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        load = self.get_object()
        load.status = TeacherMonthlyLoad.Status.APPROVED
        load.save()
        return Response({'message': 'Tasdiqlandi'})


class ScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = ScheduleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Schedule.objects.filter(
            organization=self.request.user.organization
        )

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        month = request.data.get('month')
        year  = request.data.get('year')
        title = request.data.get('title')
        org   = request.user.organization

        if not all([month, year, title]):
            return Response(
                {'error': 'month, year, title majburiy!'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Tasdiqlangan oylik yuklamalar
        loads = TeacherMonthlyLoad.objects.filter(
            teacher__organization=org,
            month=month,
            year=year,
            status=TeacherMonthlyLoad.Status.APPROVED
        ).select_related('teacher__user', 'major')

        if not loads.exists():
            return Response(
                {'error': 'Tasdiqlangan oylik yuklamalar topilmadi!'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Oy sanalarini hisoblash
        date_from = datetime.date(int(year), int(month), 1)
        if int(month) == 12:
            date_to = datetime.date(int(year) + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            date_to = datetime.date(int(year), int(month) + 1, 1) - datetime.timedelta(days=1)

        with transaction.atomic():
            schedule, created = Schedule.objects.get_or_create(
                organization=org,
                month=month,
                year=year,
                defaults={
                    'title': title,
                    'date_from': date_from,
                    'date_to': date_to,
                    'generated_by': request.user,
                }
            )
            if not created:
                schedule.entries.all().delete()

            entries = []

            for load in loads:
                teacher     = load.teacher
                major       = load.major
                total_paras = load.total_paras

                # O'qituvchi bu yo'nalishda qaysi fanlardan dars bera oladi
                try:
                    subject_assignment = TeacherSubjectAssignment.objects.get(
                        teacher=teacher,
                        major=major
                    )
                except TeacherSubjectAssignment.DoesNotExist:
                    continue

                # Bu yo'nalish guruhlari
                groups = Group.objects.filter(
                    major=major,
                    organization=org,
                    is_active=True
                )
                if not groups.exists():
                    continue

                paras_assigned = 0
                current_date   = date_from

                while current_date <= date_to and paras_assigned < total_paras:
                    weekday = current_date.isoweekday()

                    if weekday in [6, 7]:
                        current_date += datetime.timedelta(days=1)
                        continue

                    # O'qituvchining bu kundagi band vaqtlari
                    busy_times = TeacherBusyTime.objects.filter(
                        teacher=teacher,
                        date=current_date
                    )

                    for group in groups:
                        if paras_assigned >= total_paras:
                            break

                        # Guruh biriktiruvi (smena + bino)
                        try:
                            group_assignment = GroupAssignment.objects.get(
                                group=group,
                                month=month,
                                year=year
                            )
                        except GroupAssignment.DoesNotExist:
                            continue

                        building = group_assignment.building
                        shift    = group_assignment.shift

                        paras = Para.objects.filter(
                            shift=shift,
                            is_active=True
                        ).order_by('order')

                        for para in paras:
                            if paras_assigned >= total_paras:
                                break

                            # O'qituvchi band vaqtini tekshirish
                            is_busy = any(
                                bt.is_conflict(current_date, para)
                                for bt in busy_times
                            )
                            if is_busy:
                                continue

                            # O'qituvchi bu parada boshqa dars bormi
                            teacher_conflict = ScheduleEntry.objects.filter(
                                date=current_date,
                                para=para,
                                teacher=teacher
                            ).exists()
                            if teacher_conflict:
                                continue

                            # Guruh bu parada band emasmi
                            group_conflict = ScheduleEntry.objects.filter(
                                date=current_date,
                                para=para,
                                group=group
                            ).exists()
                            if group_conflict:
                                continue

                            # Fan tanlash
                            subject = subject_assignment.subjects.first()
                            if not subject:
                                continue

                            # Dars turi
                            curriculum_subject = CurriculumSubject.objects.filter(
                                curriculum__major=major,
                                subject=subject,
                                curriculum__status='active'
                            ).first()
                            lesson_type = curriculum_subject.lesson_type if curriculum_subject else 'lecture'

                            # Dars turiga mos xona tanlash
                            rooms = Room.objects.filter(
                                building=building,
                                is_active=True,
                                capacity__gte=group.student_count
                            )
                            if lesson_type == 'lecture':
                                rooms = rooms.filter(room_type__in=['lecture', 'seminar'])
                            elif lesson_type == 'practice':
                                rooms = rooms.filter(room_type='lab')

                            # Band xonalarni chiqarib tashlash
                            busy_room_ids = ScheduleEntry.objects.filter(
                                date=current_date,
                                para=para,
                                room__isnull=False
                            ).values_list('room_id', flat=True)

                            room = rooms.exclude(id__in=busy_room_ids).first()
                            if not room:
                                continue

                            entries.append(ScheduleEntry(
                                schedule=schedule,
                                teacher=teacher,
                                group=group,
                                subject=subject,
                                lesson_type=lesson_type,
                                room=room,
                                building=building,
                                para=para,
                                date=current_date,
                            ))
                            paras_assigned += 1

                    current_date += datetime.timedelta(days=1)

            ScheduleEntry.objects.bulk_create(entries)

        return Response(
            ScheduleSerializer(schedule).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        schedule = self.get_object()
        schedule.status = Schedule.Status.PUBLISHED
        schedule.save()
        return Response({'message': 'Jadval nashr etildi'})

    @action(detail=True, methods=['get'], url_path='by-group/(?P<group_id>[0-9]+)')
    def by_group(self, request, pk=None, group_id=None):
        schedule = self.get_object()
        entries  = schedule.entries.filter(
            group_id=group_id
        ).order_by('date', 'para__order')
        return Response(ScheduleEntrySerializer(entries, many=True).data)

    @action(detail=True, methods=['get'], url_path='by-teacher/(?P<teacher_id>[0-9]+)')
    def by_teacher(self, request, pk=None, teacher_id=None):
        schedule = self.get_object()
        entries  = schedule.entries.filter(
            teacher_id=teacher_id
        ).order_by('date', 'para__order')
        return Response(ScheduleEntrySerializer(entries, many=True).data)


class SubstitutionViewSet(viewsets.ModelViewSet):
    serializer_class = SubstitutionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Substitution.objects.filter(
            schedule_entry__teacher__organization=self.request.user.organization
        )

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @action(detail=False, methods=['post'], url_path='find-available')
    def find_available(self, request):
        """O'sha kuni bo'sh o'qituvchilarni topish"""
        entry_id = request.data.get('schedule_entry_id')
        date     = request.data.get('date')

        try:
            entry = ScheduleEntry.objects.get(id=entry_id)
        except ScheduleEntry.DoesNotExist:
            return Response({'error': 'Topilmadi'}, status=404)

        subject = entry.subject
        para    = entry.para

        # O'sha parada band o'qituvchilar
        busy_ids = ScheduleEntry.objects.filter(
            date=date,
            para=para
        ).values_list('teacher_id', flat=True)

        # Bo'sh va fanni o'qita oladigan o'qituvchilar
        available = Teacher.objects.filter(
            organization=self.request.user.organization,
            subject_assignments__subjects=subject,
            is_active=True
        ).exclude(id__in=busy_ids).distinct()

        return Response(TeacherSerializer(available, many=True).data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return AuditLog.objects.filter(
            organization=self.request.user.organization
        )
