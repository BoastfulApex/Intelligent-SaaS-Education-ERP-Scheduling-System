import re
import pandas as pd
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from .models import (Major, Subject, Curriculum, CurriculumBlock,
                     CurriculumSubject, Group, Shift, Para, GroupAssignment,
                     GroupDayAssignment)
from .serializers import (MajorSerializer, SubjectSerializer,
                           CurriculumSerializer, CurriculumBlockSerializer,
                           CurriculumSubjectSerializer, GroupSerializer,
                           ShiftSerializer, ParaSerializer,
                           GroupAssignmentSerializer, GroupDayAssignmentSerializer)
from permissions import (
    IsEduAdmin, IsOrgAdmin, IsOrgAdminOrReadOnly, IsEduAdminOrReadOnly,
    IsEduAdminOrMethodist, IsEduAdminWriteMethodistRead,
)


# ──────────────────────────────────────────────────────────────────────────────
#  O'QUV REJA EXCEL PARSER
# ──────────────────────────────────────────────────────────────────────────────

ROMAN = {'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'}

_ERR_WRONG_FORMAT = (
    "Xato fayl yuklandi! Ushbu fayl qo'llab-quvvatlanmaydigan formatda. "
    "Faqat rasmiy shablon faylidan foydalaning (oquv_reja_shablon.xlsx)."
)

def _validate_template(df) -> tuple[bool, str]:
    """
    Faylning to'g'ri shablon ekanligini STRUKTURAVIY tekshiradi.
    Kirill matn taqqoslashidan foydalanmaydi (encoding farqlari muammosi).

    Tekshiruvlar:
      1. Fayl kamida 5 qator va 8 ustundan iborat bo'lishi kerak
      2. Kamida bitta Roman raqamli blok qatori (I., II., ...) mavjud bo'lishi kerak
      3. Blok qatoridan keyin "1.1.", "1.2." ko'rinishidagi fan qatorlari bo'lishi kerak
      4. Kamida 2 ta Roman blok bo'lishi kerak (I., II. kabi)
    """
    _WRONG = _ERR_WRONG_FORMAT

    # 1. Minimum o'lcham tekshiruvi
    if df.shape[0] < 5:
        return False, _WRONG
    if df.shape[1] < 8:
        return False, _WRONG

    # 2. Roman raqamli blok qatorini topish
    data_start = _find_data_start(df)
    if data_start < 0:
        return False, (
            "Xato fayl yuklandi! Faylda blok qatorlari (I., II., III. ...) "
            "topilmadi. To'g'ri shablon formatini yuklang."
        )

    # 3. Blok va fan qatorlari soni tekshiruvi
    block_count   = 0
    subject_count = 0
    col_offset = 0
    if df.shape[1] > 1 and _is_block_row(df.iloc[data_start, 1]):
        col_offset = 1

    for i in range(data_start, min(data_start + 60, df.shape[0])):
        v = df.iloc[i, col_offset] if df.shape[1] > col_offset else None
        if _is_block_row(v):
            block_count += 1
        elif _is_subject_row(v):
            subject_count += 1
        elif _is_total_row(v):
            break
        # name_val ustunida total tekshiruvi
        name_v = df.iloc[i, col_offset + 1] if df.shape[1] > col_offset + 1 else None
        if _is_total_row(name_v):
            break

    if block_count < 1:
        return False, _WRONG
    if subject_count < 1:
        return False, _WRONG

    return True, ''


def _is_block_row(tr_val) -> bool:
    """I., II., III., IV. — blok qatori."""
    if tr_val is None:
        return False
    try:
        if pd.isna(tr_val):
            return False
    except (TypeError, ValueError):
        pass
    s = str(tr_val).strip().rstrip('.')
    return s in ROMAN

def _is_subject_row(tr_val) -> bool:
    """1.1., 2.3. — fan qatori."""
    if tr_val is None:
        return False
    try:
        if pd.isna(tr_val):
            return False
    except (TypeError, ValueError):
        pass
    s = str(tr_val).strip()
    return bool(re.match(r'^\d+\.\d+\.?$', s))

_TOTAL_KEYWORDS = {'jami', 'ҳаммаси', 'hammasi', 'итого', 'барчаси', 'жами'}

def _is_total_row(val) -> bool:
    """
    Jami / ҲАММАСИ / Итого — yakuniy qator.
    MUHIM: 'jami' so'zi BUTUN SO'Z sifatida tekshiriladi —
    'jamiyat', 'jamiyatning' kabi so'zlar noto'g'ri match qilmasin.
    """
    if val is None:
        return False
    try:
        if pd.isna(val):
            return False
    except (TypeError, ValueError):
        pass
    s = str(val).strip().lower()
    # Satrni so'zlarga bo'lib, har bir so'zni kalit so'zlar bilan taqqoslaymiz
    words = re.split(r'[\s:/,()\-]+', s)
    return any(w in _TOTAL_KEYWORDS for w in words if w)

def _safe_int(val) -> int:
    """NaN yoki noto'g'ri qiymatni 0 ga aylantiradi."""
    try:
        if pd.isna(val):
            return 0
        return int(float(val))
    except (TypeError, ValueError):
        return 0



def _find_data_start(df) -> int:
    """Birinchi blok qatorini topadi (I. bor qator).
    0-ustun bo'sh bo'lsa 1-ustunni ham tekshiradi."""
    for i in range(df.shape[0]):
        if _is_block_row(df.iloc[i, 0]):
            return i
        if df.shape[1] > 1 and _is_block_row(df.iloc[i, 1]):
            return i
    return -1


def _detect_hour_cols(df, data_start: int, col_offset: int) -> dict:
    """
    Soat ustunlarining joylashuvini AVTOMATIK aniqlaydi.
    Birinchi blok yoki fan qatorida B-ustundan keyin birinchi raqamli
    qiymatning pozitsiyasiga qarab format aniqlanadi.

    Format A — Kirill shablon (8._СФ_МО.xls):
      C(2)=Ҳаммаси  D(3)=АудJами  E(4)=Назарий  F(5)=Амалий
      G(6)=Кўчма    H(7)=Мустақил  I-L(8-11)=Haftalar

    Format B — Lotin shablon (12-СТМ_...xlsx):
      F(5)=Jami  G(6)=Nazariy  H(7)=Amaliy  I(8)=Ko'chma
      J(9)=Mustaqil  K-N(10-13)=Haftalar

    Qaytaradi: {'lecture', 'practice', 'field', 'independent',
                'week1', 'week2', 'week3', 'week4'} — col_offset QOSHMASDAN indekslar.
    """
    jami_ci = 2  # Default: Format A

    for i in range(data_start, min(data_start + 20, df.shape[0])):
        tr_v = df.iloc[i, col_offset] if df.shape[1] > col_offset else None
        if not (_is_block_row(tr_v) or _is_subject_row(tr_v)):
            continue
        row  = df.iloc[i]
        ncols = len(row)
        # B-ustundan (col_offset+1) keyin birinchi musbat raqamni topish
        for ci in range(col_offset + 2, min(col_offset + 12, ncols)):
            v = row.iloc[ci]
            if pd.notna(v) and str(v).strip():
                try:
                    if float(v) > 0:
                        jami_ci = ci - col_offset
                        break
                except (ValueError, TypeError):
                    pass
        break  # faqat birinchi mos qator tekshiriladi

    if jami_ci <= 3:
        total_cols = df.shape[1]
        if total_cols <= 11:
            # Format C: 14-Психологлар.xlsx — AudJami ustuni yo'q, 11 ta ustun
            # A(0)=T/r  B(1)=Nom  C(2)=Jami  D(3)=Nazariy  E(4)=Amaliy
            # F(5)=Ko'chma  G(6)=Mustaqil  H(7)=Hafta1  I(8)=Hafta2  J(9)=Hafta3  K(10)=Hafta4
            return {
                'lecture': 3, 'practice': 4, 'field': 5, 'independent': 6,
                'week1': 7, 'week2': 8, 'week3': 9, 'week4': 10,
            }
        else:
            # Format A: 8._СФ_МО.xls — AudJami ustuni bor, 12+ ustun
            # C(2)=Jami  D(3)=AudJami  E(4)=Nazariy  F(5)=Amaliy
            # G(6)=Ko'chma  H(7)=Mustaqil  I-L(8-11)=Haftalar
            return {
                'lecture': 4, 'practice': 5, 'field': 6, 'independent': 7,
                'week1': 8, 'week2': 9, 'week3': 10, 'week4': 11,
            }
    else:
        # Format B: 12-СТМ_...xlsx — Jami ancha o'ngda
        b = jami_ci
        return {
            'lecture': b + 1, 'practice': b + 2, 'field': b + 3, 'independent': b + 4,
            'week1':  b + 5,  'week2':  b + 6,  'week3':  b + 7,  'week4':  b + 8,
        }


def _generate_subject_code(name: str) -> str:
    """
    Fan nomining har bir so'zidan birinchi harf olib kod yasaydi.
    "Jismoniy tayyorgarlik"  → "JT"
    "Sport mashg'uloti"      → "SM"
    "Umumiy o'rta ta'lim"    → "UOT"
    Kichik xizmat so'zlari (va, va, bilan, ...) o'tkazib yuboriladi.
    """
    STOP_WORDS = {"va", "bilan", "uchun", "bu", "bir", "ham", "yoki", "bo'yicha"}
    words = re.split(r"[\s\-–—]+", name.strip())
    initials = []
    for w in words:
        clean = re.sub(r"[^a-zA-ZА-Яа-яёЁA-Za-zʻʼ']", '', w)
        if clean and clean.lower() not in STOP_WORDS:
            initials.append(clean[0].upper())
    return ''.join(initials) if initials else name[:4].upper()


def _get_or_create_subject(code: str, name: str, organization) -> tuple:
    """
    Fan topish yoki yaratish. Qaytaradi: (Subject, created: bool)

    Qidiruv tartibi:
      1. Nom bo'yicha aniq moslik (case-insensitive) — mavjud fanni qayta ishlatish
      2. Topilmasa — yangi Subject yaratish
         Kod = fan nomining so'zlari bosh harflaridan (masalan "JT", "SM")
         Noyobligini ta'minlash uchun raqam qo'shiladi: "JT", "JT-2", ...
    """
    clean_name = name.strip()

    # 1. Nom bo'yicha qidirish
    by_name = Subject.objects.filter(
        organization=organization,
        name__iexact=clean_name,
    ).first()
    if by_name:
        return by_name, False

    # 2. Yangi fan yaratish — kod nomning bosh harflaridan
    base_code  = _generate_subject_code(clean_name)
    final_code = base_code
    counter    = 2
    while Subject.objects.filter(organization=organization, code=final_code).exists():
        final_code = f"{base_code}-{counter}"
        counter += 1

    subj = Subject.objects.create(
        organization=organization,
        code=final_code,
        name=clean_name,
    )
    return subj, True


def parse_curriculum_excel(file, major: Major, organization,
                           curriculum_name: str = '', approved_date=None,
                           delivery_mode: str = 'offline') -> dict:
    """
    O'quv reja Excel faylini o'qib, Curriculum + Block + Subject larni yaratadi.

    Shablon formati (oquv_reja_shablon.xlsx):
      A(0)=T/r  B(1)=Fan nomi  C(2)=Jami  D(3)=Nazariy  E(4)=Amaliy
      F(5)=Ko'chma  G(6)=Mustaqil  H(7)=I-hafta  I(8)=II-hafta
      J(9)=III-hafta  K(10)=IV-hafta

    Qaytaradi:
        { 'curriculum': Curriculum, 'blocks': int, 'subjects': int,
          'warnings': list[str] }
    """
    warnings = []
    df = pd.read_excel(file, sheet_name=0, header=None)

    # ── SHABLON VALIDATSIYA ───────────────────────────────────────────────────
    valid, err_msg = _validate_template(df)
    if not valid:
        return {
            'curriculum': None,
            'blocks': 0, 'subjects': 0,
            'warnings': [err_msg],
            'error': err_msg,
        }

    # ── NOMI ─────────────────────────────────────────────────────────────────
    # Foydalanuvchi kiritgan nom → aks holda yo'nalish nomi
    course_name = curriculum_name or f"{major.name} O'quv reja"

    # ── DATA QATORLAR BOSHLANISH NUQTASI ──────────────────────────────────────
    data_start = _find_data_start(df)
    if data_start < 0:
        return {
            'curriculum': None,
            'blocks': 0, 'subjects': 0,
            'warnings': ["Excel faylda blok qatorlari (I., II., ...) topilmadi."],
        }

    # ── CURRICULUM YARATISH (mavjud bo'lsa arxivlash) ─────────────────────────
    with transaction.atomic():
        # Avvalgi faol reja arxivlash — faqat bir xil o'qitish turi (oflayn/onlayn)
        # ichida: onlayn reja yuklanganda oflayn reja tegilmasin (va aksincha), chunki
        # ular mustaqil, alohida "muddat" (approved_date) bo'yicha boshqariladi
        Curriculum.objects.filter(
            major=major,
            delivery_mode=delivery_mode,
            status=Curriculum.Status.ACTIVE,
        ).update(status=Curriculum.Status.ARCHIVED)

        curriculum = Curriculum.objects.create(
            major=major,
            delivery_mode=delivery_mode,
            name=course_name,
            status=Curriculum.Status.ACTIVE,
            approved_date=approved_date,
        )

        current_block   = None
        block_order     = 0
        subject_order   = 0
        blocks_count    = 0
        subjects_count  = 0
        subjects_new    = 0   # yangi yaratilgan
        subjects_linked = 0   # mavjud topilgan va bog'langan

        # Col offset: ba'zi fayllarda 0-ustun bo'sh, hamma narsa 1 ga siljigan
        col_offset = 0
        if df.shape[1] > 1 and _is_block_row(df.iloc[data_start, 1]):
            col_offset = 1

        # Ustunlar tartibini avtomatik aniqlash (Format A vs Format B)
        hcols = _detect_hour_cols(df, data_start, col_offset)

        for row_idx in range(data_start, df.shape[0]):
            row      = df.iloc[row_idx]
            ncols    = len(row)
            tr_val   = row.iloc[col_offset] if ncols > col_offset else None
            name_col = col_offset + 1
            name_val = str(row.iloc[name_col]).strip() if ncols > name_col and pd.notna(row.iloc[name_col]) else ''

            # ── JAMI qatori — to'xtatish ─────────────────────────────────────
            if _is_total_row(tr_val) or _is_total_row(name_val):
                break
            # Bo'sh qator — o'tkazib yuborish
            if tr_val is None or (pd.isna(tr_val) and not name_val):
                continue

            # Soat ustunlarini xavfsiz olish (blok va fan qatorlari uchun umumiy)
            def _gc(ci):
                idx = ci + col_offset
                return row.iloc[idx] if ncols > idx else None

            def _read_hours():
                return (
                    _safe_int(_gc(hcols['lecture'])),
                    _safe_int(_gc(hcols['practice'])),
                    _safe_int(_gc(hcols['field'])),
                    _safe_int(_gc(hcols['independent'])),
                    _safe_int(_gc(hcols['week1'])),
                    _safe_int(_gc(hcols['week2'])),
                    _safe_int(_gc(hcols['week3'])),
                    _safe_int(_gc(hcols['week4'])),
                )

            # ── BLOK qatori ──────────────────────────────────────────────────
            if _is_block_row(tr_val):
                block_order += 1
                subject_order = 0
                block_name = name_val if name_val else f'Blok {block_order}'
                current_block = CurriculumBlock.objects.create(
                    curriculum=curriculum,
                    name=block_name,
                    order=block_order,
                )
                blocks_count += 1
                continue

            # ── FAN qatori ───────────────────────────────────────────────────
            if _is_subject_row(tr_val) and current_block and name_val:
                subject_order += 1
                code = str(tr_val).strip().rstrip('.')
                lh, ph, fh, ih, w1, w2, w3, w4 = _read_hours()

                subj, created = _get_or_create_subject(code, name_val, organization)

                CurriculumSubject.objects.create(
                    block=current_block,
                    subject=subj,
                    order=subject_order,
                    lecture_hours=lh,
                    practice_hours=ph,
                    field_hours=fh,
                    independent_hours=ih,
                    week1_hours=w1,
                    week2_hours=w2,
                    week3_hours=w3,
                    week4_hours=w4,
                )
                subjects_count += 1
                if created:
                    subjects_new += 1
                else:
                    subjects_linked += 1

    return {
        'curriculum':     curriculum,
        'blocks':         blocks_count,
        'subjects':       subjects_count,
        'subjects_new':   subjects_new,
        'subjects_linked': subjects_linked,
        'warnings':       warnings,
    }


class MajorViewSet(viewsets.ModelViewSet):
    serializer_class = MajorSerializer
    permission_classes = [IsEduAdminOrMethodist]

    def get_queryset(self):
        return Major.objects.filter(
            organization=self.request.user.organization
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class SubjectViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectSerializer
    # O'qish har qanday autentifikatsiyalangan foydalanuvchiga ochiq (dropdown/preview
    # uchun, masalan dept_manager). Yozish faqat edu_admin+ da qoladi.
    permission_classes = [IsEduAdminOrReadOnly]

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
    serializer_class   = CurriculumSerializer
    permission_classes = [IsEduAdminOrMethodist]
    parser_classes     = [MultiPartParser, FormParser]

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

    @action(detail=False, methods=['post'], url_path='upload',
            parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        """
        POST /api/v1/curriculums/upload/
        Body (form-data):
          - file:      Excel fayl (.xlsx)  — O'quv reja
          - major_id:  Yo'nalish ID si
          - name:      O'quv reja nomi (ixtiyoriy, Excel dan olinadi)

        Logika:
          - Avvalgi faol reja arxivlanadi
          - Yangi Curriculum, CurriculumBlock, CurriculumSubject lar yaratiladi
          - Subject lar code bo'yicha topiladi yoki yangi yaratiladi
          - CurriculumBlock.department = null (edu admin keyinchalik biriktiradi)
        """
        file = request.FILES.get('file')
        if not file:
            return Response(
                {'error': '"file" maydoni talab qilinadi.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not file.name.endswith(('.xlsx', '.xls')):
            return Response(
                {'error': 'Faqat .xlsx yoki .xls fayl qabul qilinadi.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        major_id = request.data.get('major_id')
        if not major_id:
            return Response(
                {'error': '"major_id" maydoni talab qilinadi.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        major = Major.objects.filter(
            id=major_id,
            organization=request.user.organization,
        ).first()
        if not major:
            return Response(
                {'error': 'Yo\'nalish topilmadi.'},
                status=status.HTTP_404_NOT_FOUND
            )

        curriculum_name = request.data.get('name', '')
        approved_date   = request.data.get('approved_date') or None
        delivery_mode   = request.data.get('delivery_mode') or 'offline'

        try:
            result = parse_curriculum_excel(
                file=file,
                major=major,
                organization=request.user.organization,
                curriculum_name=curriculum_name,
                approved_date=approved_date,
                delivery_mode=delivery_mode,
            )
        except Exception as e:
            return Response(
                {'error': f'Excel faylni o\'qishda xato: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if result['curriculum'] is None:
            return Response(
                {'error': result['warnings'][0] if result['warnings'] else 'Noma\'lum xato.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            'success':    True,
            'message':    (
                f"O'quv reja yuklandi: {result['blocks']} blok, "
                f"{result['subjects']} fan "
                f"({result['subjects_new']} yangi, "
                f"{result['subjects_linked']} mavjud bog'landi)."
            ),
            'curriculum': CurriculumSerializer(result['curriculum']).data,
            'stats': {
                'blocks':          result['blocks'],
                'subjects':        result['subjects'],
                'subjects_new':    result['subjects_new'],
                'subjects_linked': result['subjects_linked'],
            },
            'warnings': result['warnings'],
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='template',
            permission_classes=[IsAuthenticated])
    def template(self, request):
        """
        GET /api/v1/curriculums/template/
        O'quv reja rasmiy shablon faylini yuklab beradi.
        Shablon: 14-Психологлар.xlsx formati (11 ustun)
        """
        import os
        from django.http import HttpResponse, Http404

        fixture_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'fixtures',
            'oquv_reja_shablon.xlsx',
        )

        if not os.path.exists(fixture_path):
            raise Http404("Shablon fayl topilmadi. Administrator bilan bog'laning.")

        with open(fixture_path, 'rb') as f:
            data = f.read()

        resp = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = 'attachment; filename="oquv_reja_shablon.xlsx"'
        return resp


class CurriculumBlockViewSet(viewsets.ModelViewSet):
    serializer_class = CurriculumBlockSerializer
    permission_classes = [IsEduAdminOrMethodist]

    def get_queryset(self):
        qs = CurriculumBlock.objects.filter(
            curriculum__major__organization=self.request.user.organization
        ).select_related('curriculum').prefetch_related('subjects__department', 'subjects__subject')

        curriculum_id = self.request.query_params.get('curriculum_id')
        if curriculum_id:
            qs = qs.filter(curriculum_id=curriculum_id)
        return qs

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """
        Bloklarni sudrab-tashlash orqali qayta tartiblash (CurriculumsPage.jsx — Tahrirlash oynasi).
        Body: {"curriculum_id": <id>, "block_ids": [<id>, ...]}  — yangi tartibda, birinchisi 1-blok bo'ladi.
        """
        curriculum_id = request.data.get('curriculum_id')
        block_ids = request.data.get('block_ids') or []
        if not curriculum_id or not block_ids:
            return Response({'error': 'curriculum_id va block_ids talab qilinadi'}, status=status.HTTP_400_BAD_REQUEST)

        blocks = CurriculumBlock.objects.filter(
            curriculum_id=curriculum_id,
            curriculum__major__organization=request.user.organization,
            id__in=block_ids,
        )
        if blocks.count() != len(block_ids):
            return Response({'error': "Ba'zi bloklar topilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # unique_together = ['curriculum', 'order'] to'qnashuvining oldini olish uchun
            # avval vaqtinchalik (katta) qiymatlarga o'tkaziladi, keyin yakuniy tartib qo'yiladi
            for block in blocks:
                CurriculumBlock.objects.filter(id=block.id).update(order=block.order + 10000)
            for i, block_id in enumerate(block_ids, start=1):
                CurriculumBlock.objects.filter(id=block_id).update(order=i)

        updated = CurriculumBlock.objects.filter(curriculum_id=curriculum_id).order_by('order')
        return Response(CurriculumBlockSerializer(updated, many=True).data)


class CurriculumSubjectViewSet(viewsets.ModelViewSet):
    serializer_class = CurriculumSubjectSerializer
    permission_classes = [IsEduAdminOrMethodist]
    # Haqiqiy bug: global PAGE_SIZE=20 tufayli 20 tadan ortiq fani bor o'quv rejalarda
    # "Fanlarga kafedra biriktirish" oynasi oxirgi fanlarni (masalan "Pedagogik amaliyot")
    # butunlay ko'rsatmasdi — page_size=500 chaqiruvchi tomondan yuborilsa ham jimgina
    # e'tiborga olinmasdi. Bu ro'yxat doim bitta curriculum_id bilan cheklangan (chekli
    # hajmda), shuning uchun pagination butunlay o'chiriladi (GroupDayAssignmentViewSet
    # bilan bir xil yechim).
    pagination_class = None

    def get_queryset(self):
        qs = CurriculumSubject.objects.filter(
            block__curriculum__major__organization=self.request.user.organization
        ).select_related('subject', 'block', 'department').order_by('block__order', 'order')

        curriculum_id = self.request.query_params.get('curriculum_id')
        if curriculum_id:
            qs = qs.filter(block__curriculum_id=curriculum_id)

        block_id = self.request.query_params.get('block_id')
        if block_id:
            qs = qs.filter(block_id=block_id)

        unassigned = self.request.query_params.get('unassigned')
        if unassigned in ('1', 'true'):
            qs = qs.filter(department__isnull=True)

        return qs

    @action(detail=False, methods=['post'], url_path='assign-departments')
    def assign_departments(self, request):
        """
        Fanlarga kafedra biriktirish.

        Body:
        {
          "assignments": [
            {"subject_id": 12, "department_id": 3},
            {"subject_id": 13, "department_id": 5},
            {"subject_id": 14, "department_id": null}   ← olib tashlash
          ]
        }
        """
        from organizations.models import Department

        assignments = request.data.get('assignments', [])
        if not assignments:
            return Response({'error': '"assignments" bo\'sh'}, status=400)

        org     = request.user.organization
        updated = []
        errors  = []

        with transaction.atomic():
            for item in assignments:
                subj_id = item.get('subject_id')
                dept_id = item.get('department_id')

                cs = CurriculumSubject.objects.filter(
                    id=subj_id,
                    block__curriculum__major__organization=org,
                ).first()
                if not cs:
                    errors.append({'subject_id': subj_id, 'error': 'Fan topilmadi'})
                    continue

                if dept_id:
                    # **Qoida**: faqat MUSTAQIL tayyorgarlik soatidan iborat fanga
                    # (auditoriya soati 0 — masalan "Yakuniy test sinovlari")
                    # kafedra biriktirilmaydi. Bunday fan uchun o'qituvchi ham,
                    # dars ham talab qilinmaydi — jadval generatsiyasi uni
                    # umuman vazifaga aylantirmaydi (`hours < 2` sharti).
                    # Kafedra biriktirilsa, u Taqsimot sahifasida bekorga
                    # "o'qituvchi kutayotgan fan" bo'lib ko'rinardi.
                    if cs.auditorium_hours == 0:
                        errors.append({
                            'subject_id': subj_id,
                            'error': "Faqat mustaqil tayyorgarlik fani — kafedra "
                                     "biriktirilmaydi",
                        })
                        continue
                    dept = Department.objects.filter(id=dept_id, organization=org).first()
                    if not dept:
                        errors.append({'subject_id': subj_id, 'error': 'Kafedra topilmadi'})
                        continue
                    cs.department = dept
                else:
                    cs.department = None

                cs.save(update_fields=['department'])
                updated.append(CurriculumSubjectSerializer(cs).data)

        return Response({'updated': updated, 'errors': errors})


class GroupPagination(PageNumberPagination):
    """
    Global PAGE_SIZE=20 dan farqli — ?page_size= orqali oshirish imkonini beradi.
    Guruh biriktirish kalendari (GroupAssignmentsPage.jsx) barcha guruhlarni bitta
    so'rovda (page_size=300) olishga tayanadi; page_size_query_param sozlanmagan bo'lsa
    bu parametr jimgina e'tiborga olinmay, doim faqat birinchi 20 tasi qaytardi
    (haqiqiy bug — group-day-assignments.md dagi pagination-trap bilan bir xil turkum).
    """
    page_size_query_param = 'page_size'
    max_page_size = 500


class GroupViewSet(viewsets.ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsEduAdminWriteMethodistRead]
    pagination_class = GroupPagination

    def get_queryset(self):
        return Group.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ShiftViewSet(viewsets.ModelViewSet):
    serializer_class = ShiftSerializer
    # Ilgari IsOrgAdmin edi — edu_admin frontendda /shifts ga kira olsa ham
    # backend 403 qaytarardi (haqiqiy bug). Endi edu_admin+ yozadi, methodist o'qiydi.
    permission_classes = [IsEduAdminWriteMethodistRead]

    def get_queryset(self):
        return Shift.objects.filter(
            organization=self.request.user.organization,
            is_active=True
        ).prefetch_related('paras')

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ParaViewSet(viewsets.ModelViewSet):
    serializer_class = ParaSerializer
    # Ilgari IsOrgAdmin edi — Shift bilan bir xil bug (edu_admin 403 olardi). Tuzatildi.
    permission_classes = [IsEduAdminWriteMethodistRead]

    def get_queryset(self):
        return Para.objects.filter(
            shift__organization=self.request.user.organization,
            is_active=True
        ).select_related('shift')


class GroupAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = GroupAssignmentSerializer
    permission_classes = [IsEduAdminWriteMethodistRead]

    def get_queryset(self):
        return GroupAssignment.objects.filter(
            group__organization=self.request.user.organization
        ).select_related('group', 'shift', 'building')


class GroupDayAssignmentViewSet(viewsets.ModelViewSet):
    """
    Guruh kunlik biriktiruvi — har bir sana uchun smena + xona.

    GET  /group-day-assignments/?group=1&year=2026&month=6
    POST /group-day-assignments/bulk-save/
    POST /group-day-assignments/bulk-delete/
    """
    serializer_class   = GroupDayAssignmentSerializer
    permission_classes = [IsEduAdminWriteMethodistRead]
    pagination_class   = None  # Oylik barcha kunlarni bir so'rovda qaytarish uchun

    def get_queryset(self):
        qs = GroupDayAssignment.objects.filter(
            group__organization=self.request.user.organization
        ).select_related('group', 'shift', 'building')

        group_id = self.request.query_params.get('group')
        year     = self.request.query_params.get('year')
        month    = self.request.query_params.get('month')

        if group_id:
            qs = qs.filter(group_id=group_id)
        if year and month:
            qs = qs.filter(date__year=year, date__month=month)
        elif year:
            qs = qs.filter(date__year=year)

        return qs

    @action(detail=False, methods=['post'], url_path='bulk-save')
    def bulk_save(self, request):
        """
        {
          "group": 1,
          "shift": 2,
          "room": 3,
          "dates": ["2026-06-03", "2026-06-10", ...]
        }
        """
        group_id = request.data.get('group')
        shift_id    = request.data.get('shift')
        building_id = request.data.get('building')
        dates       = request.data.get('dates', [])

        if not group_id or not dates:
            return Response(
                {'error': '"group" va "dates" maydonlari talab qilinadi.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        group = Group.objects.filter(
            id=group_id,
            organization=request.user.organization,
        ).first()
        if not group:
            return Response({'error': 'Guruh topilmadi.'}, status=status.HTTP_404_NOT_FOUND)

        created_count = updated_count = 0
        for date_str in dates:
            _, created = GroupDayAssignment.objects.update_or_create(
                group=group,
                date=date_str,
                defaults={'shift_id': shift_id, 'building_id': building_id},
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        return Response({
            'created': created_count,
            'updated': updated_count,
            'total':   len(dates),
        })

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """
        { "group": 1, "dates": ["2026-06-03"] }
        """
        group_id = request.data.get('group')
        dates    = request.data.get('dates', [])

        deleted, _ = GroupDayAssignment.objects.filter(
            group__organization=request.user.organization,
            group_id=group_id,
            date__in=dates,
        ).delete()

        return Response({'deleted': deleted})