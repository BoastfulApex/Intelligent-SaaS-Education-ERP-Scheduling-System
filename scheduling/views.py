from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from django.http import HttpResponse
import datetime
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import pandas as pd
from permissions import IsDeptManager, IsEduAdmin, IsOrgAdmin, IsDeptManagerOrReadOnly

from .models import (Teacher, TeacherBusyTime, TeacherSubjectAssignment,
                     TeacherMonthlyLoad, Schedule, ScheduleEntry,
                     Substitution, AuditLog,
                     LoadSheet, TeacherLoad, LoadDistribution)
from .serializers import (TeacherSerializer, TeacherBusyTimeSerializer,
                           TeacherSubjectAssignmentSerializer,
                           TeacherMonthlyLoadSerializer, ScheduleSerializer,
                           ScheduleEntrySerializer, SubstitutionSerializer,
                           AuditLogSerializer,
                           LoadSheetSerializer)
from academic.models import Para, GroupAssignment, Group, CurriculumSubject
from organizations.models import Room, Department


# ─── TAQSIMOT PARSER YORDAMCHI FUNKSIYALARI ───────────────────────────────────

MONTH_MAP = {
    'yanvar': 1, 'fevral': 2, 'mart': 3, 'aprel': 4,
    'may': 5, 'iyun': 6, 'iyul': 7, 'avgust': 8,
    'sentabr': 9, 'oktabr': 10, 'noyabr': 11, 'dekabr': 12,
}

STAVKA_MAP = {
    '1':    TeacherLoad.Stavka.FULL,
    '1.0':  TeacherLoad.Stavka.FULL,
    '0.5':  TeacherLoad.Stavka.HALF,
    '0.25': TeacherLoad.Stavka.QUARTER,
}


def _detect_month(sheet_name: str) -> int | None:
    """Sheet nomidan oy raqamini aniqlash."""
    return MONTH_MAP.get(sheet_name.strip().lower())


def _normalize_stavka(val) -> str:
    """Excel stavka qiymatini modeldagi choicega o'tkazish."""
    if pd.isna(val):
        return TeacherLoad.Stavka.VACANT
    s = str(val).strip().lower()
    if 'vokant' in s or 'vakant' in s:
        return TeacherLoad.Stavka.VACANT
    if 'soatbay' in s or 'soat' in s:
        return TeacherLoad.Stavka.HOURLY
    return STAVKA_MAP.get(s, TeacherLoad.Stavka.FULL)


def _try_find_teacher(full_name: str, organization) -> Teacher | None:
    """F.I.Sh bo'yicha o'qituvchini izlash."""
    if not full_name or not full_name.strip():
        return None
    parts = full_name.strip().split()
    qs = Teacher.objects.filter(organization=organization)
    for part in parts:
        if len(part) > 2:
            qs = qs.filter(user__last_name__icontains=part)
            if qs.count() == 1:
                return qs.first()
    return None


def _try_find_group(group_name: str, organization, month: int, year: int) -> Group | None:
    """Guruh nomiga mos Group topish."""
    if not group_name:
        return None
    return Group.objects.filter(
        organization=organization,
        name__icontains=group_name.strip(),
        month=month,
        year=year,
    ).first()


def _try_find_subject(module_name: str, department: Department) -> CurriculumSubject | None:
    """Modul nomi bo'yicha CurriculumSubject topish (kodni ajratib)."""
    if not module_name:
        return None
    # "3.5. Sport mashg'uloti..." → "3.5" kodini ajrat
    parts = module_name.strip().split('.')
    if len(parts) >= 2:
        code_part = '.'.join(parts[:2]).strip().rstrip('.')
        qs = CurriculumSubject.objects.filter(
            block__department=department,
            subject__code__icontains=code_part,
        )
        if qs.count() == 1:
            return qs.first()
    # Fallback: subject nomi bo'yicha qidirish
    name_part = module_name.split('.')[-1].strip()[:50]
    return CurriculumSubject.objects.filter(
        block__department=department,
        subject__name__icontains=name_part,
    ).first()


def _safe_iloc(row, idx, default=None):
    """iloc xavfsiz versiyasi — ustun mavjud bo'lmasa default qaytaradi."""
    try:
        val = row.iloc[idx]
        return val if pd.notna(val) else default
    except IndexError:
        return default


def parse_load_sheet_excel(file, department: Department, year: int,
                            organization, uploaded_by) -> dict:
    """
    Taqsimot Excel faylini o'qib, LoadSheet + TeacherLoad + LoadDistribution
    larni yaratadi. Har bir sheet = bir oy.
    Qayta yuklansa, avvalgi ma'lumotlar o'chiriladi.

    Excel format (0-indeksdan):
      Qator 0: sarlavha (ixtiyoriy)
      Qator 1: ustun nomlari — T/r | Modul | Guruh1..N | Jami | Hammasi | Stavka | F.I.Sh | Lavozim
      Qator 2+: ma'lumot qatorlari
    Ustunlar:
      0=T/r, 1=Modul, 2..22=Guruhlar (max 21 ta),
      23=Jami, 24=Hammasi, 25=Stavka, 26=F.I.Sh, 27=Lavozim
    """
    xl = pd.ExcelFile(file)
    results = []

    for sheet_name in xl.sheet_names:
        month = _detect_month(sheet_name)
        if month is None:
            continue  # 'Yopilgan guruhlar' va boshqalarni o'tkazib yuborish

        df = pd.read_excel(xl, sheet_name=sheet_name, header=None)

        if len(df) < 2:
            continue  # Bo'sh yoki faqat sarlavha bor sheet

        ncols = len(df.columns)

        # Sarlavha qatori (1-indeks) — guruh nomlari ustun bo'yicha
        header_row = df.iloc[1]
        # Guruh ustunlari: 2 dan 22 gacha (23=Jami, 24=Hammasi, 25=Stavka, 26=FISh, 27=Lavozim)
        group_cols = {}  # {col_index: group_name}
        for col_idx in range(2, min(23, ncols)):
            val = _safe_iloc(header_row, col_idx)
            if val is not None and str(val).strip():
                group_cols[col_idx] = str(val).strip()

        # Avvalgi LoadSheet ni o'chirish (qayta yuklash)
        LoadSheet.objects.filter(
            department=department, month=month, year=year
        ).delete()

        with transaction.atomic():
            load_sheet = LoadSheet.objects.create(
                department=department,
                month=month,
                year=year,
                uploaded_by=uploaded_by,
            )

            current_teacher_load = None

            for row_idx in range(2, len(df)):
                row = df.iloc[row_idx]

                tr_val    = _safe_iloc(row, 0)         # T/r
                modul_val = _safe_iloc(row, 1)         # Modul nomi
                jami_val  = _safe_iloc(row, 23, 0)     # Jami
                hammasi   = _safe_iloc(row, 24, 0)     # Hammasi
                stavka    = _safe_iloc(row, 25)        # Stavka
                fish      = _safe_iloc(row, 26, '')    # F.I.Sh
                lavozim   = _safe_iloc(row, 27, '')    # Lavozim

                # Modul nomi yo'q → oxirgi qator (izoh yoki bo'sh)
                if modul_val is None or not str(modul_val).strip():
                    continue

                module_name = str(modul_val).strip()
                try:
                    row_hours = int(jami_val) if jami_val else 0
                except (ValueError, TypeError):
                    row_hours = 0

                # Yangi o'qituvchi boshlandi (T/r soni bor)
                if tr_val is not None and str(tr_val).strip().isdigit():
                    full_name = str(fish).strip()
                    position  = str(lavozim).strip()
                    stavka_v  = _normalize_stavka(stavka)
                    try:
                        total_h = int(hammasi) if hammasi else 0
                    except (ValueError, TypeError):
                        total_h = 0

                    teacher = _try_find_teacher(full_name, organization)

                    current_teacher_load = TeacherLoad.objects.create(
                        load_sheet=load_sheet,
                        teacher=teacher,
                        full_name=full_name,
                        position=position,
                        stavka=stavka_v,
                        total_hours=total_h,
                    )

                # current_teacher_load yo'q bo'lsa o'tkazib yuborish
                if current_teacher_load is None or row_hours == 0:
                    continue

                # Guruh bo'yicha taqsimot yozuvlari
                for col_idx, g_name in group_cols.items():
                    cell_val = row.iloc[col_idx]
                    if pd.isna(cell_val) or cell_val == 0:
                        continue
                    hours = int(cell_val)
                    if hours <= 0:
                        continue

                    group   = _try_find_group(g_name, organization, month, year)
                    subject = _try_find_subject(module_name, department)

                    LoadDistribution.objects.create(
                        teacher_load=current_teacher_load,
                        curriculum_subject=subject,
                        module_name=module_name,
                        group=group,
                        group_name=g_name,
                        hours=hours,
                    )

        results.append({
            'sheet':    sheet_name,
            'month':    month,
            'year':     year,
            'teachers': load_sheet.teacher_loads.count(),
            'entries':  LoadDistribution.objects.filter(
                            teacher_load__load_sheet=load_sheet).count(),
        })

    return results


class TeacherViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherSerializer
    permission_classes = [IsDeptManager]

    def get_queryset(self):
        return Teacher.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        ).select_related('user', 'personal_room')


class TeacherBusyTimeViewSet(viewsets.ModelViewSet):
    """
    O'qituvchining band vaqtlarini boshqarish.
    Kafedra mudiri o'z kafedrasi o'qituvchilari uchun kiritadi.

    Filtrlar (query params):
      ?teacher_id=X     — faqat bitta o'qituvchi
      ?date_from=YYYY-MM-DD
      ?date_to=YYYY-MM-DD
      ?month=M&year=YYYY

    Maxsus actionlar:
      POST /bulk-create/  — bir vaqtda ko'p sana uchun band vaqt qo'shish
      GET  /by-teacher/{teacher_id}/  — o'qituvchi band vaqtlari
    """
    serializer_class   = TeacherBusyTimeSerializer
    permission_classes = [IsDeptManager]

    def get_queryset(self):
        qs     = TeacherBusyTime.objects.filter(
            teacher__organization=self.request.user.organization
        ).select_related('teacher__user')

        # Faqat o'z kafedrasi o'qituvchilari (dept_manager)
        user = self.request.user
        if user.role == 'dept_manager':
            dept = Department.objects.filter(
                manager=user, organization=user.organization
            ).first()
            if dept:
                qs = qs.filter(
                    teacher__user__department=dept
                )

        # Query param filtrlari
        params = self.request.query_params
        if teacher_id := params.get('teacher_id'):
            qs = qs.filter(teacher_id=teacher_id)
        if date_from := params.get('date_from'):
            qs = qs.filter(date__gte=date_from)
        if date_to := params.get('date_to'):
            qs = qs.filter(date__lte=date_to)
        if month := params.get('month'):
            qs = qs.filter(date__month=month)
        if year := params.get('year'):
            qs = qs.filter(date__year=year)

        return qs.order_by('date', 'teacher', 'start_time')

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        """
        Bir o'qituvchi uchun bir necha sana/vaqtni bir yo'la qo'shish.

        Body:
        {
          "teacher_id": 5,
          "is_all_day": true,         ← ixtiyoriy (default: false)
          "start_time": "09:00",      ← is_all_day=false bo'lsa majburiy
          "end_time": "11:00",
          "reason": "Konferentsiya",
          "dates": ["2026-04-07", "2026-04-08", "2026-04-09"]
        }
        """
        teacher_id = request.data.get('teacher_id')
        dates      = request.data.get('dates', [])
        is_all_day = request.data.get('is_all_day', False)
        start_time = request.data.get('start_time')
        end_time   = request.data.get('end_time')
        reason     = request.data.get('reason', '')

        if not teacher_id:
            return Response(
                {'error': 'teacher_id majburiy!'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not dates:
            return Response(
                {'error': 'dates ro\'yxati bo\'sh!'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not is_all_day and (not start_time or not end_time):
            return Response(
                {'error': 'is_all_day=False bo\'lsa start_time va end_time majburiy!'},
                status=status.HTTP_400_BAD_REQUEST
            )

        teacher = Teacher.objects.filter(
            id=teacher_id,
            organization=request.user.organization
        ).first()
        if not teacher:
            return Response(
                {'error': 'O\'qituvchi topilmadi!'},
                status=status.HTTP_404_NOT_FOUND
            )

        created  = []
        skipped  = []
        errors   = []

        for date_str in dates:
            try:
                date_val = datetime.date.fromisoformat(str(date_str).strip())
            except ValueError:
                errors.append({'date': date_str, 'error': 'Noto\'g\'ri sana formati (YYYY-MM-DD)'})
                continue

            # Serializer orqali validatsiya
            data = {
                'teacher':    teacher.id,
                'date':       date_val,
                'is_all_day': is_all_day,
                'start_time': start_time if not is_all_day else None,
                'end_time':   end_time   if not is_all_day else None,
                'reason':     reason,
            }
            ser = TeacherBusyTimeSerializer(data=data)
            if ser.is_valid():
                obj = ser.save()
                created.append(TeacherBusyTimeSerializer(obj).data)
            else:
                # Agar qoplanish bo'lsa — skip
                skipped.append({'date': date_str, 'error': ser.errors})

        return Response({
            'created': created,
            'skipped': skipped,
            'errors':  errors,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'],
            url_path=r'by-teacher/(?P<teacher_id>[0-9]+)')
    def by_teacher(self, request, teacher_id=None):
        """
        GET /teacher-busy-times/by-teacher/{teacher_id}/
        O'qituvchining band vaqtlari + xulosa.

        Query params: ?month=M&year=YYYY
        """
        qs = self.get_queryset().filter(teacher_id=teacher_id)
        params = request.query_params
        if month := params.get('month'):
            qs = qs.filter(date__month=month)
        if year := params.get('year'):
            qs = qs.filter(date__year=year)

        data = TeacherBusyTimeSerializer(qs, many=True).data
        return Response({
            'teacher_id':  teacher_id,
            'total_count': len(data),
            'busy_times':  data,
        })


class TeacherSubjectAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherSubjectAssignmentSerializer
    permission_classes = [IsDeptManager]

    def get_queryset(self):
        qs = TeacherSubjectAssignment.objects.filter(
            teacher__organization=self.request.user.organization
        ).select_related('teacher__user', 'major').prefetch_related('subjects')
        major_id = self.request.query_params.get('major_id')
        if major_id:
            qs = qs.filter(major_id=major_id)
        teacher_id = self.request.query_params.get('teacher_id')
        if teacher_id:
            qs = qs.filter(teacher_id=teacher_id)
        return qs

    @action(detail=False, methods=['post'], url_path='bulk-assign')
    def bulk_assign(self, request):
        """
        POST /api/v1/teacher-subject-assignments/bulk-assign/
        Bir yo'la ko'p o'qituvchiga fanlar biriktirish (yoki olib tashlash).

        Body:
        {
          "major_id": 1,
          "assignments": [
            {"teacher_id": 3, "subject_ids": [1, 2, 5]},
            {"teacher_id": 4, "subject_ids": [2, 3]},
            {"teacher_id": 5, "subject_ids": []}     ← bo'sh = biriktirishni olib tashlash
          ]
        }
        """
        from academic.models import Major, Subject as AcSubject

        major_id    = request.data.get('major_id')
        assignments = request.data.get('assignments', [])
        org         = request.user.organization

        if not major_id:
            return Response({'error': 'major_id majburiy'}, status=status.HTTP_400_BAD_REQUEST)

        major = Major.objects.filter(id=major_id, organization=org).first()
        if not major:
            return Response({'error': 'Yo\'nalish topilmadi'}, status=status.HTTP_404_NOT_FOUND)

        results = []
        with transaction.atomic():
            for item in assignments:
                teacher_id  = item.get('teacher_id')
                subject_ids = item.get('subject_ids', [])

                teacher = Teacher.objects.filter(id=teacher_id, organization=org).first()
                if not teacher:
                    continue

                if not subject_ids:
                    # Bo'sh — mavjud biriktirishni o'chirish
                    TeacherSubjectAssignment.objects.filter(
                        teacher=teacher, major=major
                    ).delete()
                    results.append({
                        'teacher_id': teacher_id,
                        'action': 'removed',
                        'subjects': 0,
                    })
                    continue

                subjects = AcSubject.objects.filter(
                    id__in=subject_ids, organization=org
                )
                assignment, created = TeacherSubjectAssignment.objects.get_or_create(
                    teacher=teacher, major=major
                )
                assignment.subjects.set(subjects)
                results.append({
                    'teacher_id':  teacher_id,
                    'teacher_name': teacher.user.get_full_name(),
                    'action':      'created' if created else 'updated',
                    'subjects':    subjects.count(),
                })

        return Response({
            'success': True,
            'message': f'{len(results)} ta o\'qituvchi uchun fan biriktiruvi yangilandi.',
            'results': results,
        }, status=status.HTTP_200_OK)


class TeacherMonthlyLoadViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherMonthlyLoadSerializer
    permission_classes = [IsDeptManager]

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
    permission_classes = [IsEduAdmin]

    def get_queryset(self):
        return Schedule.objects.filter(
            organization=self.request.user.organization
        )

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        """
        POST /api/v1/schedules/generate/
        Body: { month, year, title, date_from(ixtiyoriy), date_to(ixtiyoriy), time_limit(ixtiyoriy) }

        Ketma-ketlik:
          1. LoadDistribution dan vazifalar olinadi
          2. OR-Tools CP-SAT yordamida jadval tuziladi
          3. ScheduleEntry lar yaratiladi
        """
        from .solver import generate_schedule

        month      = request.data.get('month')
        year       = request.data.get('year')
        title      = request.data.get('title')
        org        = request.user.organization
        time_limit = int(request.data.get('time_limit', 60))

        if not all([month, year, title]):
            return Response(
                {'error': 'month, year, title majburiy!'},
                status=status.HTTP_400_BAD_REQUEST
            )

        month = int(month)
        year  = int(year)

        # Oy sanalarini hisoblash
        date_from_str = request.data.get('date_from')
        date_to_str   = request.data.get('date_to')

        if date_from_str:
            date_from = datetime.date.fromisoformat(date_from_str)
        else:
            date_from = datetime.date(year, month, 1)

        if date_to_str:
            date_to = datetime.date.fromisoformat(date_to_str)
        else:
            if month == 12:
                date_to = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                date_to = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

        # LoadDistribution mavjudligini tekshirish
        from .models import LoadDistribution
        if not LoadDistribution.objects.filter(
            teacher_load__load_sheet__department__organization=org,
            teacher_load__load_sheet__month=month,
            teacher_load__load_sheet__year=year,
        ).exists():
            return Response(
                {'error': f'{month}/{year} uchun taqsimot yuklanmagan! '
                          'Avval load-sheets/upload/ orqali taqsimot yuklang.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            schedule, created = Schedule.objects.get_or_create(
                organization=org,
                month=month,
                year=year,
                defaults={
                    'title':        title,
                    'date_from':    date_from,
                    'date_to':      date_to,
                    'generated_by': request.user,
                }
            )
            if not created:
                # Qayta generatsiya — avvalgi yozuvlar o'chiriladi
                schedule.entries.all().delete()
                schedule.status = Schedule.Status.DRAFT
                schedule.save()

            # OR-Tools solver
            result = generate_schedule(
                schedule=schedule,
                organization=org,
                month=month,
                year=year,
                time_limit_seconds=time_limit,
            )

            entries  = result['entries']
            stats    = result['stats']
            warnings = result['warnings']

            if entries:
                ScheduleEntry.objects.bulk_create(entries)

        response_data = {
            'schedule':  ScheduleSerializer(schedule).data,
            'stats':     stats,
            'warnings':  warnings,
            'created':   len(entries),
        }

        http_status = (
            status.HTTP_201_CREATED if entries
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return Response(response_data, status=http_status)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        schedule = self.get_object()
        schedule.status = Schedule.Status.PUBLISHED
        schedule.save()
        return Response({'message': 'Jadval nashr etildi'})

    @action(detail=True, methods=['get'], url_path='by-group/(?P<group_id>[0-9]+)',
            permission_classes=[IsAuthenticated])
    def by_group(self, request, pk=None, group_id=None):
        schedule = self.get_object()
        entries  = schedule.entries.filter(
            group_id=group_id
        ).order_by('date', 'para__order')
        return Response(ScheduleEntrySerializer(entries, many=True).data)

    @action(detail=True, methods=['get'], url_path='by-teacher/(?P<teacher_id>[0-9]+)',
            permission_classes=[IsAuthenticated])
    def by_teacher(self, request, pk=None, teacher_id=None):
        schedule = self.get_object()
        entries  = schedule.entries.filter(
            teacher_id=teacher_id
        ).order_by('date', 'para__order')
        return Response(ScheduleEntrySerializer(entries, many=True).data)


class ScheduleEntryViewSet(viewsets.ModelViewSet):
    """
    Jadval elementlari (darslar) — alohida CRUD.

    Filtrlar:
      ?schedule_id=X
      ?group_id=X
      ?teacher_id=X
      ?date=YYYY-MM-DD
      ?date_from=YYYY-MM-DD
      ?date_to=YYYY-MM-DD
    """
    serializer_class   = ScheduleEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = (
            ScheduleEntry.objects
            .filter(schedule__organization=self.request.user.organization)
            .select_related(
                'teacher__user', 'group', 'subject',
                'para', 'room', 'building', 'schedule'
            )
            .order_by('date', 'para__order')
        )
        p = self.request.query_params
        if v := p.get('schedule_id'): qs = qs.filter(schedule_id=v)
        if v := p.get('group_id'):    qs = qs.filter(group_id=v)
        if v := p.get('teacher_id'): qs = qs.filter(teacher_id=v)
        if v := p.get('date'):        qs = qs.filter(date=v)
        if v := p.get('date_from'):   qs = qs.filter(date__gte=v)
        if v := p.get('date_to'):     qs = qs.filter(date__lte=v)
        return qs


class SubstitutionViewSet(viewsets.ModelViewSet):
    serializer_class = SubstitutionSerializer
    permission_classes = [IsDeptManager]

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
    permission_classes = [IsOrgAdmin]

    def get_queryset(self):
        return AuditLog.objects.filter(
            organization=self.request.user.organization
        )


# ─────────────────────────────────────────────
#  TAQSIMOT VIEWSET
# ─────────────────────────────────────────────

class LoadSheetViewSet(viewsets.ModelViewSet):
    """
    Taqsimot varaqlari ro'yxati, ko'rish va o'chirish.
    Yuklash uchun: POST /load-sheets/upload/
    """
    http_method_names = ['get', 'delete', 'head', 'options']  # PUT/PATCH yo'q
    serializer_class   = LoadSheetSerializer
    permission_classes = [IsDeptManager]
    parser_classes     = [MultiPartParser, FormParser]

    def get_queryset(self):
        user = self.request.user
        qs   = LoadSheet.objects.filter(
            department__organization=user.organization
        ).select_related('department', 'uploaded_by').prefetch_related(
            'teacher_loads__distributions'
        )
        # Dept manager faqat o'z kafedrasi
        if user.role == 'dept_manager':
            dept = Department.objects.filter(
                manager=user, organization=user.organization
            ).first()
            if dept:
                qs = qs.filter(department=dept)
        return qs

    @action(detail=False, methods=['post'], url_path='upload',
            parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        """
        POST /api/v1/load-sheets/upload/
        Body (form-data):
          - file: Excel fayl (.xlsx)
          - department_id: kafedra ID (ixtiyoriy, dept_manager uchun avtomatik)
          - year: yil (default: joriy yil)
        """
        file = request.FILES.get('file')
        if not file:
            return Response(
                {'error': 'Excel fayl yuklanmadi. "file" field talab qilinadi.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not file.name.endswith(('.xlsx', '.xls')):
            return Response(
                {'error': 'Faqat .xlsx yoki .xls formatdagi fayllar qabul qilinadi.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user

        # Kafedrani aniqlash
        dept_id = request.data.get('department_id')
        if dept_id:
            dept = Department.objects.filter(
                id=dept_id, organization=user.organization
            ).first()
            if not dept:
                return Response(
                    {'error': 'Kafedra topilmadi.'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            dept = Department.objects.filter(
                manager=user, organization=user.organization
            ).first()
            if not dept:
                return Response(
                    {'error': 'Siz hech qaysi kafedraning mudiri emassiz. department_id bering.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        year = int(request.data.get('year', datetime.date.today().year))

        try:
            results = parse_load_sheet_excel(
                file=file,
                department=dept,
                year=year,
                organization=user.organization,
                uploaded_by=user,
            )
        except Exception as e:
            return Response(
                {'error': f'Excel faylni o\'qishda xato: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not results:
            return Response(
                {'error': 'Excel faylda tan olinadigan oy sheeti topilmadi '
                          '(Yanvar, Fevral, ... Dekabr bo\'lishi kerak).'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            'success': True,
            'message': f'{len(results)} ta oy muvaffaqiyatli yuklandi.',
            'sheets':  results,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='curriculum-preview',
            permission_classes=[IsAuthenticated])
    def curriculum_preview(self, request):
        """
        GET /api/v1/load-sheets/curriculum-preview/?month=M&year=YYYY
        O'sha oydagi guruhlarning o'quv rejasidagi fanlar va soatlarini qaytaradi.
        """
        from academic.models import GroupAssignment, Curriculum

        month = request.query_params.get('month')
        year  = request.query_params.get('year')

        if not month or not year:
            return Response({'error': 'month va year talab qilinadi'}, status=400)

        try:
            month = int(month)
            year  = int(year)
        except ValueError:
            return Response({'error': 'month va year son bo\'lishi kerak'}, status=400)

        org = request.user.organization

        # O'sha oydagi guruh biriktiruv (GroupAssignment)
        assignments = (
            GroupAssignment.objects
            .filter(group__organization=org, month=month, year=year)
            .select_related('group__major', 'shift', 'building')
            .order_by('group__name')
        )

        if not assignments.exists():
            return Response({
                'month': month, 'year': year,
                'total_groups': 0, 'groups': [],
                'warning': f"{month}/{year} uchun guruh biriktiruvi topilmadi. "
                           "Avval 'Guruh biriktiruv' qismida smena va bino biriktiring.",
            })

        result = []
        for ga in assignments:
            group = ga.group
            if not group.major_id:
                continue

            # Guruhning faol o'quv rejasi
            curriculum = (
                Curriculum.objects
                .filter(major_id=group.major_id, status='active')
                .prefetch_related(
                    'blocks__subjects__subject',
                    'blocks__subjects__department',
                )
                .first()
            )
            if not curriculum:
                result.append({
                    'group_id':       group.id,
                    'group_name':     group.name,
                    'major_name':     group.major.name,
                    'shift_name':     ga.shift.name if ga.shift else '—',
                    'building_name':  ga.building.name if ga.building else '—',
                    'curriculum':     None,
                    'subjects':       [],
                    'warning':        f"{group.major.name} uchun faol o'quv reja topilmadi.",
                })
                continue

            subjects = []
            for block in curriculum.blocks.all():
                for cs in block.subjects.all():
                    subjects.append({
                        'curriculum_subject_id': cs.id,
                        'block_name':       block.name or f'{block.order}-blok',
                        'subject_id':       cs.subject_id,
                        'subject_name':     cs.subject.name,
                        'subject_code':     cs.subject.code,
                        'department_id':    cs.department_id,
                        'department_name':  cs.department.name if cs.department else None,
                        'lecture_hours':    cs.lecture_hours,
                        'practice_hours':   cs.practice_hours,
                        'field_hours':      cs.field_hours,
                        'independent_hours':cs.independent_hours,
                        'auditorium_hours': cs.auditorium_hours,
                        'grand_total_hours':cs.grand_total_hours,
                        'week1_hours':      cs.week1_hours,
                        'week2_hours':      cs.week2_hours,
                        'week3_hours':      cs.week3_hours,
                        'week4_hours':      cs.week4_hours,
                    })

            result.append({
                'group_id':      group.id,
                'group_name':    group.name,
                'major_name':    group.major.name,
                'shift_name':    ga.shift.name if ga.shift else '—',
                'building_name': ga.building.name if ga.building else '—',
                'curriculum':    curriculum.name,
                'subjects':      subjects,
                'warning':       None,
            })

        return Response({
            'month':        month,
            'year':         year,
            'total_groups': len(result),
            'groups':       result,
        })

    @action(detail=False, methods=['get'], url_path='template',
            permission_classes=[IsAuthenticated])
    def template(self, request):
        """
        GET /api/v1/load-sheets/template/
        Taqsimot Excel shablonini yuklab beradi.
        """
        wb = openpyxl.Workbook()

        MONTHS_UZ = [
            'Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun',
            'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr',
        ]

        header_fill  = PatternFill('solid', fgColor='1F4E79')
        header_font  = Font(bold=True, color='FFFFFF', size=10)
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        thin = Side(style='thin', color='AAAAAA')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        example_groups = ['A-1', 'A-2', 'B-1', 'B-2']
        # Col layout: 0=T/r, 1=Modul, 2..5=Groups (4 ta misol), 6=Jami, 7=Hammasi, 8=Stavka, 9=FISh, 10=Lavozim
        # But we keep the real format: cols 2-22 for groups (21 max), 23=Jami, 24=Hammasi, 25=Stavka, 26=FISh, 27=Lavozim
        GROUP_START = 2
        GROUP_END   = 5   # 4 ta misol guruh (kengaytirish mumkin)
        COL_JAMI    = 23
        COL_HAMMASI = 24
        COL_STAVKA  = 25
        COL_FISH    = 26
        COL_LAVOZIM = 27
        TOTAL_COLS  = 28

        for month_name in MONTHS_UZ:
            ws = wb.create_sheet(title=month_name)

            # Qator 1 (index 0): Sarlavha
            ws.cell(row=1, column=1, value=f'{month_name} oyi — Taqsimot jadvali')
            ws.cell(row=1, column=1).font = Font(bold=True, size=12)
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=TOTAL_COLS)
            ws.cell(row=1, column=1).alignment = center_align

            # Qator 2 (index 1): Ustun nomlari
            headers = ['T/r', 'Modul nomi / Fan'] + \
                      [f'Guruh {i+1}' for i in range(21)] + \
                      ['Jami', 'Hammasi', 'Stavka', 'F.I.Sh', 'Lavozim']

            for col_idx, h in enumerate(headers, start=1):
                cell = ws.cell(row=2, column=col_idx, value=h)
                cell.fill      = header_fill
                cell.font      = header_font
                cell.alignment = center_align
                cell.border    = border

            # Misol qatorlar (index 2, 3)
            example_rows = [
                [1, '1.1. Jismoniy tayyorgarlik', 16, 8, 8, 8,
                 *([''] * 17), 40, 80, '1', 'Aliyev Vohid Rahimovich', 'Dotsent'],
                ['', '1.2. Nazariya', 8, 4, 4, 4,
                 *([''] * 17), 20, '', '', '', ''],
                [2, '2.1. Taktika', 12, 6, 6, 6,
                 *([''] * 17), 30, 60, '0.5', 'Karimov Jasur Baxtiyorovich', "O'qituvchi"],
            ]
            for r_idx, row_data in enumerate(example_rows, start=3):
                for c_idx, val in enumerate(row_data, start=1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=val if val != '' else None)
                    cell.border = border
                    cell.alignment = Alignment(horizontal='center', vertical='center')

            # Ustun kengliklari
            ws.column_dimensions['A'].width = 5    # T/r
            ws.column_dimensions['B'].width = 35   # Modul
            for col_letter in [ws.cell(row=1, column=c).column_letter for c in range(3, 24)]:
                ws.column_dimensions[col_letter].width = 8  # Guruhlar
            ws.column_dimensions[ws.cell(row=1, column=24).column_letter].width = 7   # Jami
            ws.column_dimensions[ws.cell(row=1, column=25).column_letter].width = 9   # Hammasi
            ws.column_dimensions[ws.cell(row=1, column=26).column_letter].width = 8   # Stavka
            ws.column_dimensions[ws.cell(row=1, column=27).column_letter].width = 25  # FISh
            ws.column_dimensions[ws.cell(row=1, column=28).column_letter].width = 15  # Lavozim

            ws.row_dimensions[2].height = 40

        # Birinchi bo'sh sheetni o'chirish
        if 'Sheet' in wb.sheetnames:
            del wb['Sheet']

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        response = HttpResponse(
            buffer.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="taqsimot_shablon.xlsx"'
        return response
