"""
OR-Tools CP-SAT asosida jadval generatsiya.

Manbalar:
  - GroupSubject        → guruh + o'quv reja fani + o'qituvchi biriktiruvi (haqiqiy
                          "Taqsimot" manbai — LoadSheetPage.jsx, Excel talab qilmaydi)
  - Curriculum          → guruhning faol o'quv rejasi (get_active_for_date)
  - Para                → kunning vaqt uyachalari (1-para, 2-para, ...)
  - GroupDayAssignment  → guruh qaysi smena + binoda (kunlik kalendar — "Guruh biriktirish")
  - TeacherBusyTime     → o'qituvchi band sanalar/vaqtlar
  - Room                → xonalar (tur, sig'im)
  - CurriculumSubject   → haftalik soat taqsimoti (week1..week4)

**Muhim (haqiqiy bug, tuzatilgan)**: avval bu fayl vazifalarni faqat eski
`LoadDistribution` modelidan (Excel yuklash oqimi orqali to'ldiriladigan) olar edi —
lekin loyihaning hozirgi asosiy Taqsimot oqimi (`.claude/rules/load-sheet-teacher-
assignment.md`) Excel talab qilmaydi, u to'g'ridan-to'g'ri `GroupSubject`ga yozadi.
Natijada foydalanuvchi Taqsimot sahifasida barcha fanlarga o'qituvchi tayinlagan
bo'lsa ham, `generate` har doim "taqsimot yuklanmagan" xatosi qaytarardi. Batafsil:
`.claude/rules/schedule-generation.md`.

Onlayn (Zoom) darslar: `Group.delivery_mode == 'online'` bo'lsa, guruhga faqat smena
kerak — bino/xona talab qilinmaydi va tanlanmaydi (ScheduleEntry.is_online=True,
room/building bo'sh qoladi).

Chiqish:
  - list[ScheduleEntry] — DB ga yozilishga tayyor yozuvlar
"""

import os
import datetime
import calendar
from dataclasses import dataclass, field
from collections import defaultdict

from ortools.sat.python import cp_model

from academic.models import (
    Para, Group, CurriculumSubject, GroupDayAssignment, DeliveryMode, Curriculum,
)
from organizations.models import Room, Building, Department
from .models import (
    Teacher, TeacherBusyTime, GroupSubject,
    ScheduleEntry, Schedule,
)


# ──────────────────────────────────────────────────────────────────────────────
#  MA'LUMOT TUZILMALARI
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Task:
    """Bitta GroupSubject (guruh+fan+o'qituvchi) yozuvidan yaratilgan vazifa."""
    dist_id:    int          # GroupSubject.id (traceability uchun, vakant bo'lsa 0)
    teacher_id: int | None   # None = vakant/o'qituvchi biriktirilmagan
    group_id:   int
    subject_id: int
    room_type:  str          # 'lecture' | 'practice' | 'field' | 'independent'
    hours:      int          # bajariladigan umumiy soat
    paras_needed: int        # hours // 2
    group_start: datetime.date   # guruhning shu oydagi haqiqiy boshlanish sanasi
    group_end:   datetime.date   # guruhning shu oydagi haqiqiy tugash sanasi
    # Bino task darajasida SAQLANMAYDI — guruh oy davomida turli binolarga
    # biriktirilgan bo'lishi mumkin, shuning uchun bino har bir (vazifa, sana)
    # juftligi uchun `day_map`dan alohida hisoblanadi (slot yaratish bosqichida).
    is_online:    bool = False        # Group.delivery_mode == 'online' — xona/bino kerak emas
    requires_computer_room: bool = False   # Subject.requires_computer_room (IT/AKT fani)
    # Kafedra — viloyat binolarida kafedralar Department.order bo'yicha
    # NAVBATMA-NAVBAT chiqadi (bir kafedra tugagach keyingisi)
    department_id: int | None = None
    # Ko'chma mashg'ulot vazifasimi (CurriculumSubject.field_hours dan) —
    # bunday darslar o'quv jarayonining OXIRIGA, ketma-ket va XONASIZ qo'yiladi
    is_field:     bool = False
    # Auditoriya vazifasining nechta parasi NAZARIY deb belgilanishi kerak.
    # Qolganlari AMALIY bo'ladi. Belgilash solver ishlagandan KEYIN, joylashgan
    # paralarni vaqt bo'yicha tartiblab bajariladi (9-bo'lim) — shuning uchun
    # "avval nazariy, keyin amaliy" tartibi QURILISHI BO'YICHA ta'minlanadi,
    # hech qanday cheklov kerak emas.
    lec_paras:    int = 0

    # Haftalik taqsimot (0 = cheklov yo'q) — guruhning o'z group_start'idan hisoblanadi
    week_hours: list = field(default_factory=lambda: [0, 0, 0, 0])


# Kafedra navbati oynasining chegaralaridagi zaxira (kun). Navbat qat'iy devor
# emas — ortib qolgan slotlarni keyingi/oldingi kafedra to'ldira olishi kerak
# (foydalanuvchi qoidasi 1.5). Batafsil: `dept_window` hisoblanadigan joyda.
DEPT_WINDOW_SLACK = 2

# Bir kunda viloyatda bo'lishi mumkin bo'lgan o'qituvchilar soni — o'sha kuni
# viloyatda dars oladigan GURUHLAR soniga qo'shiladigan zaxira (foydalanuvchi
# qoidasi 2: "nechta guruh bo'lsa n+2 ta o'qituvchi").
REGIONAL_TEACHER_SLACK = 3

# Viloyatga kelgan o'qituvchi bir kunda kamida NECHTA para o'tishi shart.
# 1 = QAT'IY qoida o'chirilgan (joriy holat), 2 = "1 para uchun kelmasin".
#
# **QAT'IY variant sinaldi va RAD ETILDI** (o'lchangan, 900s, real dump):
#
# |                        | qoida BILAN | qoida SIZ |
# |------------------------|-------------|-----------|
# | joylashgan             | 1283        | 1283      |
# | 1-BOSQICH vaqti        | **585s**    | **80s**   |
# | kuniga 1 para          | 0/113 (0%)  | 21/113 (19%) |
# | bo'sh kunsiz o'qituvchi| 15/24 (62%) | **22/24 (92%)** |
# | jami bo'sh kun         | 12          | **4**     |
#
# Ya'ni qat'iy qoida 8 ta QO'SHIMCHA bo'sh kun keltirib chiqaradi va solverni
# 7 barobar sekinlashtiradi (generatsiya 4 daqiqadan 12–15 daqiqaga cho'ziladi).
# Foydalanuvchi uchun bo'sh kun muhimroq ("bo'sh kun bo'lmasligi kerak"),
# 1 paralik kunlar esa 5–10% atrofida maqbul deb belgilangan.
#
# Qo'lda tuzilgan may jadvalida ham qoida 100% bajarilmaydi: viloyatdagi
# 104 o'qituvchi-kunning 3 tasi (3%) bir paralik — ya'ni odamlar ham buni
# QAT'IY emas, moslashuvchan qo'llaydi.
#
# Buning o'rniga 1 paralik kunlar YUMSHOQ yo'l bilan kamaytiriladi:
# `REGIONAL_PRESENCE_WEIGHT` (quyida) — darslar soni o'zgarmagani uchun
# o'qituvchi-kunlar kamaysa, qolgan kunlar avtomatik to'ladi.
REGIONAL_MIN_PARAS_PER_DAY = 1

# Viloyatda o'qituvchining KUN ICHIDA bo'sh parasi (teshigi) taqiqlansinmi.
# True  = teshik 0% (qat'iy), lekin bo'sh KUNLAR biroz ko'payadi
# False = teshik ~10-13% (qo'lda tuzilgan jadvalda ham 11%), bo'sh kun kamroq
# Foydalanuvchi qarori: viloyatda bo'sh KUN bo'sh PARAdan qimmatroq
# (komandirovkada ortiqcha kun = yo'l + turar joy), shuning uchun kun ustuvor.
REGIONAL_NO_GAP_WITHIN_DAY = True

# VILOYAT bosqichida bitta (o'qituvchi, kun) — ya'ni komandirovka kuni —
# uchun jazo vazni. Uni oshirish 1 paralik kunlarni kamaytiradi (kunlar
# kamayadi, qolganlari to'ladi), lekin bo'sh kun jazolari (100/5000) bilan
# raqobatlashadi — juda katta qilinsa kunlar siyraklashib bo'shliq paydo
# bo'lishi mumkin. O'lchab tanlanadi.
REGIONAL_PRESENCE_WEIGHT = 150

# **SINALGAN VA RAD ETILGAN — "ikki safar"**: ko'chma + oddiy fani bor
# o'qituvchi viloyatga ikki marta borsin (boshida oddiy darslar, uyga qaytadi,
# oxirida ko'chma), bo'sh kun esa HAR SAFAR ICHIDA o'lchansin degan g'oya.
# Amalga oshirildi va o'lchandi (`MAX_SPLIT_TEACHERS=2`, `MIN_TRIP_GAP_DAYS=7`):
# uchala ishga tushirishda ham **1274/1283 — 9 ta DARS YO'QOLDI**, bo'sh kunsiz
# o'qituvchi esa 23/24 dan 18–22 ga tushdi.
# Sabab: 7 kunlik ajratishni ta'minlash uchun oddiy darslar safarining oynasi
# qisqartiriladi, qat'iy chegara esa o'sha oynadan tashqaridagi darslarni siqib
# chiqaradi. Ustiga aralash yuklamali o'qituvchi bu ma'lumotda 2 emas, 4 ta
# ekan — ularning ikkitasida "safarlar orasi" 1–2 kun bo'lib chiqdi, ya'ni
# maqsad ham bajarilmadi.
# Xulosa: bo'sh kun BITTA yaxlit safar bo'yicha o'lchanadi (quyidagicha).


# O'qituvchining viloyatdagi ketma-ket kun bloki uchun QAT'IY chegara zaxirasi
# (kun). Tor blok yumshoq jazo bilan tortiladi, qat'iy chegara esa shu zaxira
# bilan kengroq — CP-SAT'ga darslarni sig'dirish erkinligi qolishi uchun.
TEACHER_WINDOW_MARGIN = 2

# Ko'chma mashg'ulot kunida boshqa fanlar FAQAT shu tartibgacha bo'lgan
# paralarda o'tilishi mumkin (foydalanuvchi qoidasi 1.3 / 2.2) — undan keyin
# tinglovchilar amaliyot uchun tashqariga chiqib ketadi.
FIELD_DAY_OTHER_MAX_PARA = 2

# Ko'chma mashg'ulot oynasi — guruh davrining OXIRGI shuncha kuni (eng oxirgi
# kun baribir taqiqlangan). Foydalanuvchi qoidasi: "ko'chma mashg'ulotlar
# oxirgi 7- yoki 8-kundan boshlab bo'lishi mumkin".
# Ko'chma soati ko'p guruhlarda oyna avtomatik kengayadi (kerakli kun + 1),
# aks holda soatlar sig'masdi.
FIELD_WINDOW_DAYS = 8


@dataclass
class Slot:
    """Bitta vaqt uyachasi: sana + para."""
    date:     datetime.date
    para_id:  int
    week_idx: int   # 0..3


@dataclass
class ResolvedAssignment:
    """Bitta (guruh, sana) juftligi uchun HAQIQIY smena/bino/onlayn holati."""
    shift_id:    int
    building_id: int | None
    is_online:   bool


# ──────────────────────────────────────────────────────────────────────────────
#  YORDAMCHI FUNKSIYALAR
# ──────────────────────────────────────────────────────────────────────────────

def _get_working_days(date_from: datetime.date,
                      date_to: datetime.date) -> list[datetime.date]:
    """Du–Sha kunlarni qaytaradi (7=Yakshanba o'tkaziladi)."""
    days = []
    d = date_from
    while d <= date_to:
        if d.isoweekday() <= 6:   # 1=Du ... 6=Sha
            days.append(d)
        d += datetime.timedelta(days=1)
    return days


def _week_index(date: datetime.date, date_from: datetime.date) -> int:
    """Sananing o'sha oydagi hafta indeksi (0..3)."""
    delta = (date - date_from).days
    return min(delta // 7, 3)


def _build_slots(working_days: list[datetime.date],
                 date_from: datetime.date,
                 paras: list) -> list[Slot]:
    """Barcha (sana × para) kombinatsiyalarini qaytaradi."""
    slots = []
    for d in working_days:
        for p in paras:
            slots.append(Slot(
                date=d,
                para_id=p.id,
                week_idx=_week_index(d, date_from),
            ))
    return slots


def _teacher_busy_set(teacher_id: int,
                      date_from: datetime.date,
                      date_to: datetime.date,
                      paras: list) -> set[tuple]:
    """O'qituvchi band bo'lgan (date, para_id) juftlarini qaytaradi."""
    busy = set()
    busy_times = TeacherBusyTime.objects.filter(
        teacher_id=teacher_id,
        date__range=(date_from, date_to),
    )
    for bt in busy_times:
        for p in paras:
            if bt.is_conflict(bt.date, p):
                busy.add((bt.date, p.id))
    return busy


def _resolve_group_day_map(organization,
                           date_from: datetime.date,
                           date_to: datetime.date) -> dict[tuple, ResolvedAssignment]:
    """
    Har bir (guruh, sana) juftligi uchun HAQIQIY kunlik smena/bino/onlayn holatini
    qaytaradi — `{(group_id, date): ResolvedAssignment}`.

    Manba — `GroupDayAssignment` ("Guruh biriktirish" kalendari, kunlik yozuvlar).
    Eski `academic.models.GroupAssignment` (oylik) endi ISHLATILMAYDI — hech qanday
    frontend sahifasi unga yozmaydi (o'lik jadval edi), shuning uchun jadval
    generatsiyasi undan foydalansa har doim "smena/bino biriktirilmagan" berib
    o'tkazib yuborardi.

    **Haqiqiy bug (tuzatilgan)**: avval bu funksiya guruh uchun shu davrdagi ENG
    ERTA sanali yozuvni butun oy uchun "vakillik qiluvchi" sifatida ishlatardi.
    Lekin production ma'lumotlarida (tekshirildi) bir guruh oy davomida haqiqatan
    TURLI binolarga biriktirilgan bo'lishi mumkin (masalan birinchi hafta bir
    binoda, keyingi haftalar boshqa binoda) — bunday holda boshqa kunlar uchun
    noto'g'ri (birinchi kunning) bino ishlatilib qolardi. Endi har bir KUNNING
    o'z haqiqiy smena/binosi alohida saqlanadi va shunga mos ishlatiladi.

    Guruh `delivery_mode='online'` bo'lsa — `building_id=None` bo'lishi kutiladi va
    `is_online=True` qaytariladi (bino talab qilinmaydi, faqat smena kerak).
    """
    groups_by_id = {
        g.id: g for g in Group.objects.filter(organization=organization)
    }

    day_assignments = (
        GroupDayAssignment.objects
        .filter(group__organization=organization, date__range=(date_from, date_to),
                shift__isnull=False)
        .select_related('shift', 'building')
    )

    result: dict[tuple, ResolvedAssignment] = {}
    for da in day_assignments:
        group = groups_by_id.get(da.group_id)
        is_online = bool(group and group.delivery_mode == DeliveryMode.ONLINE)
        result[(da.group_id, da.date)] = ResolvedAssignment(
            shift_id=da.shift_id,
            building_id=da.building_id,
            is_online=is_online,
        )
    return result


def _select_room(building_id: int,
                 lesson_type: str,
                 min_capacity: int,
                 used_room_ids: set[int],
                 requires_computer_room: bool = False) -> Room | None:
    """Bo'sh, mos xona topish."""
    qs = Room.objects.filter(
        building_id=building_id,
        is_active=True,
        capacity__gte=min_capacity,
    ).exclude(id__in=used_room_ids)

    def _by_lesson_type(base_qs):
        if lesson_type in ('lecture',):
            return base_qs.filter(room_type__in=['lecture', 'seminar'])
        if lesson_type in ('practice', 'field'):
            return base_qs.filter(room_type__in=['lab', 'seminar'])
        return base_qs

    if requires_computer_room:
        # IT/AKT fani — avval 'Kompyuter xonasi' turidagi xona izlanadi. Binoda bunday
        # xona bo'lmasa/band bo'lsa — dars xonasiz qolib ketmasligi uchun oddiy
        # (dars turiga mos) xonaga tushiladi (fallback).
        room = qs.filter(room_type='computer').first()
        if room:
            return room
        return _by_lesson_type(qs).first()

    return _by_lesson_type(qs).first()


# ──────────────────────────────────────────────────────────────────────────────
#  ASOSIY SOLVER
# ──────────────────────────────────────────────────────────────────────────────

def generate_schedule(
    schedule: Schedule,
    organization,
    month: int,
    year: int,
    time_limit_seconds: int = 60,
    progress_cb=None,
) -> dict:
    """
    OR-Tools CP-SAT yordamida jadval generatsiya qiladi.

    Qaytaradi:
        {
          'entries': list[ScheduleEntry],   — DB ga yozilmagan (bulk_create uchun)
          'stats':   dict,                  — generatsiya statistikasi
          'warnings': list[str],            — ogohlantirish xabarlar
        }
    """
    warnings = []

    # ── PROGRESS: foydalanuvchiga tushunarli tilda jarayonni xabar qilish ────
    # `progress_cb(foiz, qadam_nomi, izoh)` — texnik bo'lmagan foydalanuvchi
    # (edu_admin) uchun yozilgan matnlar. Solver ichidagi bosqich nomlari
    # (`VILOYAT-BO'SHLIQ` va h.k.) diagnostika uchun, bu matnlar esa UI uchun.
    def _p(pct, step, detail=''):
        if progress_cb:
            try:
                progress_cb(pct, step, detail)
            except Exception:   # progress yozish jadvalni buzmasligi kerak
                pass

    _p(3, "Ma'lumotlar o'qilmoqda",
       "Guruhlar, o'quv rejalar, o'qituvchilar va binolar bazadan olinmoqda.")

    # ── 1. SANALAR ────────────────────────────────────────────────────────────
    date_from = schedule.date_from
    date_to   = schedule.date_to
    working_days = _get_working_days(date_from, date_to)

    if not working_days:
        return {'entries': [], 'stats': {}, 'warnings': ['Ish kunlari topilmadi!']}

    # ── 2. PARALAR ────────────────────────────────────────────────────────────
    all_paras = list(Para.objects.filter(is_active=True).order_by('order'))
    if not all_paras:
        return {'entries': [], 'stats': {}, 'warnings': ['Paralar kiritilmagan!']}

    para_by_id = {p.id: p for p in all_paras}

    # Bir kundagi maksimal para soni (eng "uzun" smena bo'yicha) — "og'ir"
    # o'qituvchini aniqlashda va ko'chma mashg'ulot sig'imini hisoblashda kerak
    _paras_by_shift: defaultdict[int, int] = defaultdict(int)
    for p in all_paras:
        _paras_by_shift[p.shift_id] += 1
    max_paras_per_day = max(_paras_by_shift.values()) if _paras_by_shift else 0

    # ── 3. GURUHLAR (o'sha oyda kunlik biriktiruvi bor) ───────────────────────
    # `curriculum_preview`dagi (`scheduling/views.py`) bilan bir xil naqsh — "oyning
    # vakillik qiluvchi ma'lumoti" GroupDayAssignment orqali aniqlanadi.
    group_ids_with_da = (
        GroupDayAssignment.objects
        .filter(group__organization=organization, date__year=year, date__month=month)
        .values_list('group_id', flat=True)
        .distinct()
    )
    groups = list(
        Group.objects
        .filter(id__in=group_ids_with_da, organization=organization, major__isnull=False)
        .select_related('major')
    )

    if not groups:
        return {
            'entries': [],
            'stats': {},
            'warnings': [f'{month}/{year} uchun guruh kunlik biriktiruvi topilmadi.'],
        }

    # ── 4. GURUH → KUNLIK SMENA + BINO + PARALAR ─────────────────────────────
    # `{(group_id, date): ResolvedAssignment}` — har bir kunning o'z haqiqiy
    # smena/binosi (guruh oy davomida turli binolarga biriktirilgan bo'lishi
    # mumkin — haqiqiy bug, tuzatilgan, .claude/rules/schedule-generation.md).
    day_map = _resolve_group_day_map(organization, date_from, date_to)
    groups_with_da = {gid for (gid, _d) in day_map}

    # ── 5. VAZIFALAR (Task) YARATISH — GroupSubject (haqiqiy Taqsimot manbai) ──
    tasks: list[Task] = []
    unassigned_count = 0
    month_end_day = calendar.monthrange(year, month)[1]
    target_date = datetime.date(year, month, month_end_day)

    # Bir xil yo'nalish (Major) + ta'lim turidagi guruhlar bir xil faol o'quv rejani
    # ishlatadi (target_date barcha guruhlar uchun bir xil) — har bir guruh uchun
    # qayta so'rov yubormaslik uchun (major_id, delivery_mode) bo'yicha keshlanadi.
    # Ko'p guruhli tashkilotlarda bu N so'rovni bir nechta so'rovga tushiradi.
    curriculum_cache: dict[tuple, object] = {}

    def _get_curriculum(major, delivery_mode):
        key = (major.id, delivery_mode)
        if key not in curriculum_cache:
            curriculum_cache[key] = Curriculum.get_active_for_date(
                major, target_date=target_date, delivery_mode=delivery_mode,
                queryset=Curriculum.objects.prefetch_related('blocks__subjects__subject'),
            )
        return curriculum_cache[key]

    # Barcha guruhlar uchun GroupSubject'lar BITTA so'rovda olinadi (har guruh uchun
    # alohida so'rov yubormaslik uchun) — (group_id, curriculum_subject_id) bo'yicha
    # lug'atga yig'iladi.
    gs_by_group_cs: dict[tuple, object] = {
        (gs.group_id, gs.curriculum_subject_id): gs
        for gs in GroupSubject.objects.filter(
            group_id__in=[g.id for g in groups],
            teacher__isnull=False,
            is_vacant=False,
        ).select_related('teacher')
    }

    for group in groups:
        curriculum = _get_curriculum(group.major, group.delivery_mode)
        if not curriculum:
            warnings.append(
                f"Guruh #{group.id} ({group.name}) uchun faol o'quv reja topilmadi — "
                "o'tkazib yuborildi."
            )
            continue

        if group.id not in groups_with_da:
            warnings.append(
                f"Guruh #{group.id} uchun smena biriktirilmagan — o'tkazib yuborildi."
            )
            continue

        # Guruhning shu oydagi o'z muddati — Schedule global davri bilan kesishmasi.
        # Har bir guruh o'z boshlanish sanasidan hisoblangan haftalik taqsimotga ega
        # bo'lishi kerak (masalan 3-sentabrda boshlangan guruh va 7-sentabrda
        # boshlangan guruhning "1-hafta"si turli kunlarga to'g'ri keladi).
        g_start = max(group.start_date or date_from, date_from)
        g_end   = min(group.end_date or date_to, date_to)
        if g_start > g_end:
            warnings.append(
                f"Guruh #{group.id} ({group.name}) muddati ({group.start_date}—"
                f"{group.end_date}) {month}/{year} bilan mos kelmaydi — o'tkazib yuborildi."
            )
            continue

        # `is_online` — Group.delivery_mode'dan, doim bir xil (kunlik biriktiruvdan
        # farqli, guruh oy davomida onlayn/oflayn turini o'zgartirmaydi). Bino esa
        # ENDI task darajasida emas, har bir (vazifa, sana) juftligi uchun
        # `day_map`dan alohida hisoblanadi (pastda, 7-bo'lim) — chunki guruh oy
        # davomida turli binolarga biriktirilgan bo'lishi mumkin.
        is_online = group.delivery_mode == DeliveryMode.ONLINE

        for block in curriculum.blocks.all():
            for cs in block.subjects.select_related('subject').all():
                gs = gs_by_group_cs.get((group.id, cs.id))
                # Fanga o'qituvchi biriktirilmagan yoki vakant deb belgilangan bo'lsa
                # ham — dars jadvaldan butunlay tashlab yuborilmaydi, balki
                # `teacher_id=None` bilan joylashtiriladi (guruhning o'sha kuni
                # bo'sh qolib ketmasligi uchun, "hali odam yo'q" holatini ko'rsatib
                # turadi). O'qituvchi to'qnashuvi cheklovi (Constraint 2) bunday
                # vazifalarga qo'llanilmaydi — chunki haqiqiy odam yo'q, bir-biriga
                # zid kelmaydi (haqiqiy so'rov: .claude/rules/schedule-generation.md).
                if gs:
                    teacher_id = gs.teacher_id
                    dist_id = gs.id
                else:
                    teacher_id = None
                    dist_id = 0
                    unassigned_count += 1

                requires_computer_room = bool(cs.subject and cs.subject.requires_computer_room)

                week_hours = [
                    cs.week1_hours or 0,
                    cs.week2_hours or 0,
                    cs.week3_hours or 0,
                    cs.week4_hours or 0,
                ]

                # ── KO'CHMA MASHG'ULOTNI ALOHIDA VAZIFAGA AJRATISH ────────────
                # **Haqiqiy bug (tuzatilgan)**: avval `hours = cs.auditorium_hours`
                # (= nazariy + amaliy + KO'CHMA) bitta vazifaga solinardi va
                # `_lesson_type_for_subject()` fanga BITTA tur berardi
                # (ustuvorlik `lecture > practice > field`). Natijada ko'chma
                # mashg'ulot soatlari "ma'ruza" deb belgilanib, oddiy auditoriyaga
                # joylashtirilardi — real ma'lumotda ko'chma soati bor 22 fandan
                # 20 tasi shunday ARALASH edi, ya'ni ularning ko'chma qismi
                # butunlay ko'rinmas bo'lib qolgan.
                # Bitta CurriculumSubject IKKITA vazifaga bo'linadi:
                #   1) auditoriya (nazariy + amaliy) — xonali. Nazariy/amaliy
                #      BELGISI solver ishlagandan keyin qo'yiladi (`lec_paras`)
                #   2) ko'chma (field_hours) — o'quv jarayonining OXIRIDA,
                #      ketma-ket, XONASIZ (tinglovchilar tashqarida amaliyot qiladi)
                #
                # **Haqiqiy bug #2 (tuzatilgan)**: avval auditoriya vazifasiga
                # BITTA tur berilardi (`'lecture' if cs.lecture_hours > 0 else
                # 'practice'`), ya'ni nazariy soati bor HAR QANDAY fanning
                # amaliy qismi ham "nazariy" deb belgilanardi. O'lchangan:
                #   o'quv rejada  1050 soat nazariy / 982 soat amaliy (48% amaliy)
                #   generatsiyada 322 dars nazariy / 30 dars amaliy  ( 8% amaliy)
                # ya'ni 182 ta aralash fanning amaliy qismi ko'rinmay qolgan.
                # Qo'lda tuzilgan haqiqiy jadvalda 149 nazariy / 206 amaliy.
                #
                # **SINALGAN VA RAD ETILGAN — alohida vazifaga ajratish**:
                # dastlab nazariy va amaliy IKKITA alohida `Task` qilingan edi,
                # tartib esa CP-SAT cheklovi bilan ta'minlangan. O'lchangan
                # oqibatlari (real dump, sentabr 2026):
                #   vazifalar soni  300 -> 506  (model deyarli ikki barobar)
                #   vaqt            240s yetardi -> 420–800s ham yetmasdi
                #   qat'iy tartib   1270/1283 (13 ta DARS YO'QOLDI)
                #   yumshoq tartib  1283/1283, lekin 67–76 ta buzilish (36–40%)
                # Ya'ni ikkala talab (dars yo'qolmasin + tartib saqlansin) bir
                # vaqtda bajarilmasdi.
                #
                # Yechim: nazariy va amaliy — bir xil o'qituvchi, guruh va fan,
                # ular faqat BELGISI bilan farq qiladi. Shuning uchun solverga
                # ikkita vazifa berish shart emas: bitta vazifa joylashtiriladi,
                # so'ng joylashgan paralar VAQT BO'YICHA tartiblanib, birinchi
                # `lec_paras` tasi "nazariy", qolgani "amaliy" deb belgilanadi
                # (9-bo'lim). Tartib QURILISHI BO'YICHA to'g'ri chiqadi —
                # cheklov ham, qo'shimcha o'zgaruvchi ham kerak emas.
                lec_hours   = cs.lecture_hours or 0
                prac_hours  = cs.practice_hours or 0
                field_hours = cs.field_hours or 0
                aud_hours   = lec_hours + prac_hours

                def _mk(hours_, lesson_type_, is_field_, week_hours_,
                        lec_paras_=0):
                    return Task(
                        dist_id=dist_id,
                        teacher_id=teacher_id,
                        group_id=group.id,
                        subject_id=cs.subject_id,
                        room_type=lesson_type_,
                        hours=hours_,
                        paras_needed=hours_ // 2,
                        group_start=g_start,
                        group_end=g_end,
                        is_online=is_online,
                        requires_computer_room=requires_computer_room,
                        department_id=cs.department_id,
                        is_field=is_field_,
                        lec_paras=lec_paras_,
                        week_hours=week_hours_,
                    )

                if aud_hours >= 2:
                    # `room_type` xona tanlash uchun kerak — vazifada nazariy
                    # soat bo'lsa ma'ruza xonasi mos keladi, aks holda amaliy.
                    # Yakuniy dars TURI esa har bir para uchun alohida,
                    # `lec_paras` bo'yicha qo'yiladi.
                    tasks.append(_mk(
                        aud_hours,
                        'lecture' if lec_hours > 0 else 'practice',
                        False,
                        week_hours,
                        lec_paras_=lec_hours // 2,
                    ))
                if field_hours >= 2:
                    # Ko'chma mashg'ulotga haftalik reja QO'LLANILMAYDI — u
                    # o'quv jarayonining oxiriga qo'yiladi (haftalik taqsimot
                    # o'quv rejada butun fan uchun berilgan, ko'chma qismi uchun
                    # alohida emas; ikkala vazifaga ham qo'llansa kvota ikki
                    # baravar bo'lib ketardi)
                    tasks.append(_mk(field_hours, 'field', True, [0, 0, 0, 0]))
                if aud_hours < 2 and field_hours < 2:
                    continue

    if unassigned_count:
        warnings.append(
            f"Jami {unassigned_count} ta fanga o'qituvchi biriktirilmagan yoki vakant "
            "deb belgilangan — jadvalga \"Vakant\" sifatida (o'qituvchisiz) joylashtirildi."
        )

    _p(10, "Darslar ro'yxati tayyorlandi",
       f"{len(tasks)} ta fan-guruh juftligi topildi. Endi ularni kunlar va "
       "paralarga taqsimlash boshlanadi.")

    if not tasks:
        return {
            'entries': [],
            'stats': {},
            'warnings': warnings + ['Hech qanday vazifa yaratilmadi.'],
        }

    # ── 6. SLOT YARATISH (sana × para) ───────────────────────────────────────
    # Har guruh HAR BIR KUNNING o'z haqiqiy smenasidagi paralaridan foydalanadi
    # (`day_map` — guruh oy davomida turli smenaga o'tishi mumkin, garchi
    # productionda odatda smena o'zgarmasa ham, bino ko'pincha o'zgaradi).
    all_slot_keys: set[tuple] = set()
    for t in tasks:
        for d in working_days:
            da = day_map.get((t.group_id, d))
            if da is None:
                continue
            shift_para_ids = [p.id for p in all_paras if p.shift_id == da.shift_id]
            for pid in shift_para_ids:
                all_slot_keys.add((d, pid))

    slots = [Slot(date=d, para_id=p, week_idx=_week_index(d, date_from))
             for (d, p) in sorted(all_slot_keys)]
    slot_index = {(s.date, s.para_id): i for i, s in enumerate(slots)}

    # ── 7. OR-TOOLS MODEL ─────────────────────────────────────────────────────
    model  = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    # Maqsad funksiyasi murakkablashgani sayin (kunlik zichlik + viloyat safarlari)
    # qidiruv og'irlashadi — mavjud yadrolardan foydalanamiz. Serverni butunlay
    # egallab qo'ymaslik uchun 2 ta yadro bo'sh qoldiriladi, chegara [4, 12].
    solver.parameters.num_search_workers = max(4, min(12, (os.cpu_count() or 4) - 2))

    # x[task_i, slot_j] = 1 → task_i slot_j da joylashtirildi
    # `slot_building` — har bir haqiqatan yaratilgan (ti,si) uchun SHU KUNGA tegishli
    # haqiqiy bino (guruh oy davomida turli binoda bo'lishi mumkin — 9-bo'limda
    # ScheduleEntry yaratishda ishlatiladi, `task.building_id` o'rniga).
    # ── VILOYATDA KAFEDRA OYNALARI (navbat) — oldindan hisoblanadi ───────────
    # **Nega optimizatorga qoldirilmaydi (o'lchangan)**: kafedra navbati
    # dastlab yumshoq jazo sifatida yozilgan edi (`dept_order_terms`,
    # `dept_spread_terms`). Bosqich ishladi (obj=28660), lekin natija umuman
    # o'zgarmadi — ikkala kafedra ham 3..20 kunlarni to'liq egallab turdi.
    # Sabab: kafedralarni ajratish STRUKTURAVIY qayta joylashtirish — yuzlab
    # darsni bir vaqtda ko'chirishni talab qiladi, CP-SAT esa issiq startdan
    # (`add_hint`) bunday katta sakrashni topa olmaydi, faqat mayda
    # yaxshilanishlarni ko'radi.
    # Yechim: navbatni Python'da DETERMINISTIK hisoblab, x o'zgaruvchilarini
    # o'sha oynadan tashqariga umuman yaratmaslik. Bu ham natijani kafolatlaydi,
    # ham modelni sezilarli kichraytiradi.
    #
    # Algoritm (har guruh uchun alohida): guruhning viloyatdagi kunlari
    # tartiblanadi; kafedralar `Department.order` bo'yicha navbatga qo'yiladi;
    # har kafedraga o'z para talabiga yetadigan ketma-ket kunlar bloki
    # ajratiladi. Chegara kuni IKKALA kafedraga ham ochiq qoldiriladi — bir kun
    # ichida oldingi kafedra tugab, keyingisi boshlanishi mumkin (aks holda
    # kunning yarmi behuda ketardi).
    regional_building_ids_early = set(
        Building.objects.filter(organization=organization, is_regional=True)
        .values_list('id', flat=True)
    )
    dept_order_map = dict(
        Department.objects.filter(organization=organization)
        .values_list('id', 'order')
    )
    # (group_id, department_id) -> (birinchi_kun_indeksi, oxirgi_kun_indeksi)
    dept_window: dict[tuple, tuple] = {}
    if regional_building_ids_early:
        paras_per_shift: defaultdict[int, int] = defaultdict(int)
        for p in all_paras:
            paras_per_shift[p.shift_id] += 1

        need_by_gd: defaultdict[tuple, int] = defaultdict(int)
        for task in tasks:
            if task.department_id is None:
                continue
            need_by_gd[(task.group_id, task.department_id)] += task.paras_needed

        groups_reg: defaultdict[int, list] = defaultdict(list)
        for (gid, d), da in day_map.items():
            if da.building_id in regional_building_ids_early:
                groups_reg[gid].append((d, paras_per_shift.get(da.shift_id, 0)))

        for gid, day_caps in groups_reg.items():
            day_caps.sort()
            depts = sorted(
                {d_id for (g_, d_id) in need_by_gd if g_ == gid},
                key=lambda i: (dept_order_map.get(i, 999), i),
            )
            if len(depts) < 2:
                continue  # bitta kafedra — navbat tushunchasi qo'llanmaydi
            n_days = len(day_caps)
            cursor = 0      # joriy kun indeksi
            used_in_day = 0  # shu kunda allaqachon band qilingan para
            for pos, d_id in enumerate(depts):
                need = need_by_gd[(gid, d_id)]
                start = cursor
                while need > 0 and cursor < n_days:
                    free = day_caps[cursor][1] - used_in_day
                    take = min(free, need)
                    need -= take
                    used_in_day += take
                    if used_in_day >= day_caps[cursor][1]:
                        cursor += 1
                        used_in_day = 0
                end = min(cursor, n_days - 1)
                if pos == len(depts) - 1:
                    end = n_days - 1   # oxirgi kafedra — qolgan barcha kunlar
                # ── OYNA ZAXIRASI (foydalanuvchi qoidasi 1.5) ────────────────
                # "1-kafedra o'tib bo'lmasdan 2-kafedra boshlansa ham, ortib
                # qolgan slotlarni to'ldirish uchun boshqa kafedradan o'qituvchi
                # olish mumkin" — ya'ni navbat QAT'IY devor emas, chegaralarda
                # ustma-ust tushishi mumkin. Aks holda kafedra bloki ichida
                # ortib qolgan slotlar (masalan kafedra talabi 9 para, blok
                # sig'imi 12) behuda bo'sh qolib, darslar yo'qolardi.
                # Tartibning O'ZI baribir saqlanadi — `dept_order_terms` /
                # `dept_spread_terms` jazolari uni yumshoq ushlab turadi.
                s_i = max(0, start - DEPT_WINDOW_SLACK)
                e_i = min(n_days - 1, end + DEPT_WINDOW_SLACK)
                dept_window[(gid, d_id)] = (day_caps[s_i][0], day_caps[e_i][0])

    # ── KO'CHMA MASHG'ULOT OYNASI: guruh davrining oxirgi qismi ──────────────
    # Har guruh uchun "shu sanadan boshlab ko'chma mashg'ulot o'tsa bo'ladi"
    # chegarasi. Guruhning ko'chma paralari nechta kunni egallashi hisoblanadi
    # va oxiridan shuncha kun (+50% zaxira, kamida +1 kun) ajratiladi — zaxira
    # kerak, chunki bir kunda guruh boshqa fanlarni ham o'tishi mumkin.
    # Har guruh uchun ko'chma mashg'ulotga AJRATILGAN kunlar to'plami.
    # **Foydalanuvchi qoidalari (barcha binolarda)**:
    #   1. ko'chma mashg'ulot davr OXIRIDA bo'lsin
    #   2. lekin ENG OXIRGI kunga tushmasin (u yakuniy ish uchun qoladi)
    #   3. ketma-ket bo'lsin, orasiga BOSHQA FAN qo'shilmasin
    #
    # **Nega oyna emas, aniq KUNLAR to'plami (real ma'lumotda o'lchangan)**:
    # avval "shu sanadan keyin ko'chma o'tsa bo'ladi" degan yumshoq oyna
    # (+50% zaxira) ishlatilgan edi. Har bir ko'chma FAN alohida ketma-ket
    # chiqardi va ko'chma kunida boshqa fan bo'lmasdi, LEKIN guruhning ko'chma
    # DAVRI yaxlit emasdi — bazadagi #19 jadvalda "Trener-seleksioner" guruhida
    # 26.09 ko'chma, 28.09 oddiy darslar, 29.09 yana ko'chma bo'lib chiqdi;
    # "Sport turlari" guruhida esa ko'chma 28.09 da tugab, 29–30.09 da yana
    # oddiy darslar qolgan edi (ya'ni ko'chma oxirida emas).
    #
    # Yechim: guruhning oxirgi kunlari (eng oxirgisidan tashqari) ko'chma uchun
    # ajratiladi. Ko'chma fanlar FAQAT o'sha kunlarga tushadi; o'sha kunlarda
    # oddiy fanlar esa faqat 1- va 2-parada o'tilishi mumkin (quyida, `gf`).
    field_days: dict[int, set] = {}
    field_min_days: dict[int, int] = {}   # guruhning ko'chma bloki uchun MINIMAL kun
    field_need: defaultdict[int, int] = defaultdict(int)
    field_task_count: defaultdict[int, int] = defaultdict(int)
    for task in tasks:
        if task.is_field:
            field_need[task.group_id] += task.paras_needed
            field_task_count[task.group_id] += 1
    # Viloyatda dars oladigan guruhlar — ular uchun ko'chma oynasi KENG
    # (foydalanuvchi qoidasi: "ko'chmani oxiriga mixlangan bo'lsa, unda
    # boshroqqa tortish kerak, bunga mumkin"). Sabab: ko'chma blok davr
    # oxiriga qattiq bog'langanda, ham oddiy fan ham ko'chma o'tadigan
    # o'qituvchi viloyatga IKKI MARTA borishga majbur bo'lardi — bu esa
    # "bo'sh kun bo'lmasin" qoidasini buzardi.
    regional_groups_early = {
        gid_ for (gid_, _d), da_ in day_map.items()
        if da_.building_id in regional_building_ids_early
    }
    if field_need:
        days_by_group: defaultdict[int, list] = defaultdict(list)
        for (gid, d), da in day_map.items():
            days_by_group[gid].append((d, _paras_by_shift.get(da.shift_id, 0)))
        for gid, need in field_need.items():
            day_caps = sorted(days_by_group.get(gid, []))
            usable = day_caps[:-1]      # ENG OXIRGI kun ko'chma uchun taqiqlangan
            if not usable or need <= 0:
                continue
            # **Sinalgan va RAD ETILGAN**: viloyat guruhlari uchun ko'chma
            # oynasini BUTUN davrga ochish (oxirgi kundan tashqari) —
            # foydalanuvchi "ko'chmani boshroqqa tortish mumkin" deganidan
            # keyin. Natija: 1-bosqich `OPTIMAL 1278/1283` qaytardi, ya'ni
            # **5 ta dars strukturaviy imkonsiz** bo'lib qoldi. Sabab —
            # oynaning o'zi emas, `teacher_window` greedy'si: ko'chma
            # o'qituvchisining ruxsat etilgan oralig'i butun davrga
            # kengaygach, greedy ularga yomon blok tanlab, qat'iy chegara
            # orqali darslarni siqib chiqarardi. Shuning uchun oyna
            # davrning OXIRGI qismida qoladi, "boshroqqa tortish" esa
            # `field_early` vaznini pasaytirish orqali beriladi (quyida).
            acc = 0
            chosen = []
            for d_, cap in reversed(usable):
                chosen.append(d_)
                acc += cap
                if acc >= need:
                    break

            # ── KO'CHMA BLOKI UCHUN MINIMAL KUN SONI ────────────────────────
            # **Haqiqiy muammo (real jadvalda o'lchangan)**: "ko'chma kunida
            # boshqa fan 1–2-parada bo'lishi mumkin" qoidasi qo'yilgach solver
            # ko'chmani kuniga 1 paradan qo'yib, qolgan paralarni oddiy fanlar
            # bilan to'ldirishni afzal ko'rdi — natijada ko'chma blok
            # SUYULTIRILDI: "Gimnastika sport turlari" 12 ta ko'chma parani
            # 4 kun o'rniga 7 kunga, "Regbi" 6 kunga yoydi (kunlarda 1/3, 2/3
            # zichlik). Ketma-ketlik tekshiruvi buni ko'rmaydi — kunlar
            # yonma-yon, lekin blok ikki barobar cho'zilgan.
            # Yechim: guruhning ko'chma kunlari soni eng yirik sig'imli kunlar
            # bo'yicha hisoblangan MINIMUMdan oshmasin (quyida qat'iy cheklov).
            big_caps = sorted((c for _d, c in day_caps), reverse=True)
            acc_min, k_min = 0, 0
            for c in big_caps:
                if acc_min >= need:
                    break
                acc_min += c
                k_min += 1
            field_min_days[gid] = max(1, k_min)

            # ── OYNA: davrning OXIRGI `FIELD_WINDOW_DAYS` kuni ──────────────
            # Foydalanuvchi qoidasi: "ko'chma mashg'ulotlar oxirgi 7- yoki
            # 8-kundan boshlab bo'lishi mumkin". Avval oyna hisoblab
            # topilardi (kerakli kun + 50% zaxira) — bu ham taxminan shu
            # natijani berardi (UO'TM guruhlarida 6 kun), lekin guruhdan
            # guruhga o'zgarib turardi va bashorat qilib bo'lmasdi.
            #
            # **Muhim**: oyna kengligi SIG'IMGA ta'sir qilmaydi — kun bandligi
            # (`gf`) faqat ko'chma dars HAQIQATAN tushgan kunni cheklaydi,
            # oyna ichidagi ishlatilmagan kunlar oddiy fanlarga to'liq ochiq
            # qoladi. Tor oyna esa BARCHA guruhlarning ko'chma darsini bir xil
            # kunlarga majburlab, o'qituvchi to'qnashuvi tufayli soatlarni
            # joylashtirmay qo'yardi.
            #
            # **Sinalgan va RAD ETILGAN**: oynani BUTUN davrga ochish (viloyat
            # guruhlari uchun) — 1-bosqich `OPTIMAL 1278/1283` qaytardi, ya'ni
            # 5 ta dars strukturaviy imkonsiz bo'lib qoldi (sabab: `teacher_window`
            # greedy'si ko'chma o'qituvchilariga yomon blok tanlab qolardi).
            n_win = max(len(chosen) + 1, FIELD_WINDOW_DAYS)
            chosen = [d_ for d_, _c in usable[-n_win:]]
            field_days[gid] = set(chosen)

    # ── VILOYATDA O'QITUVCHI OYNASI — STRUKTURAVIY (hal qiluvchi) ────────────
    # **Muammo (o'lchangan)**: "borgan o'qituvchi bo'sh kun qoldirmasin" +
    # "bir kunda ko'pi bilan n+2 o'qituvchi" ikkalasini SOLVERGA qoldirganda
    # u 226 soniyada ham 24 o'qituvchidan 5 tasida bo'shliqni yopolmadi.
    # Bu imkonsizlik EMAS edi: hisob bo'yicha minimal kerakli o'qituvchi-kun
    # 95, sig'im esa 18 kun × 7 = 126. Ya'ni yechim bor, lekin qidiruv maydoni
    # (24 o'qituvchi × 18 kun) juda katta va CP-SAT issiq startdan bunday
    # STRUKTURAVIY qayta joylashtirishni topa olmaydi.
    #
    # Yechim — aynan `dept_window` bilan bir xil naqsh: navbatni Python'da
    # DETERMINISTIK hisoblab, x o'zgaruvchilarini oynadan tashqariga umuman
    # yaratmaslik. Har o'qituvchiga o'z yukiga yetadigan KETMA-KET kunlar
    # bloki beriladi, blok tanlashda esa kunlik o'qituvchi limiti hisobga
    # olinadi. Shunda ikkala qoida ham QURILISH bo'yicha kafolatlanadi.
    #
    # Ko'chma mashg'uloti bor o'qituvchi uchun oyna ko'chma blokning oxiriga
    # BOG'LANADI — aks holda u viloyatga ikki marta borishga majbur bo'lardi
    # (oddiy fanlari o'rtada, ko'chmasi oxirida).
    teacher_window: dict[int, tuple] = {}        # tor blok — yumshoq tortish
    teacher_window_hard: dict[int, tuple] = {}   # kengaytirilgan — qat'iy chegara
    if regional_building_ids_early and max_paras_per_day:
        groups_by_reg_day: defaultdict[object, set] = defaultdict(set)
        for (gid_, d_), da_ in day_map.items():
            if da_.building_id in regional_building_ids_early:
                groups_by_reg_day[d_].add(gid_)
        reg_day_list = sorted(groups_by_reg_day)
        day_pos = {d: i for i, d in enumerate(reg_day_list)}
        cap_left = [len(groups_by_reg_day[d]) + REGIONAL_TEACHER_SLACK
                    for d in reg_day_list]

        # Guruhning har bir viloyat kunidagi para sig'imi — oyna tanlashda
        # "bu o'qituvchining darslari shu kunlarga jismonan sig'adimi" degan
        # savolga javob berish uchun kerak (faqat o'qituvchilar sonini
        # hisoblash YETARLI EMAS — o'lchangan: shunda 9 ta dars yo'qolgan edi,
        # chunki bir necha o'qituvchi bitta guruhning o'sha kunidagi 4 ta
        # parasi uchun raqobatlashib qolardi).
        group_cap_left: dict[tuple, int] = {}
        for (gid_, d_), da_ in day_map.items():
            if da_.building_id in regional_building_ids_early and d_ in day_pos:
                group_cap_left[(gid_, day_pos[d_])] = _paras_by_shift.get(
                    da_.shift_id, 0)

        t_need: defaultdict[int, int] = defaultdict(int)
        t_group_need: defaultdict[int, defaultdict] = defaultdict(
            lambda: defaultdict(int))
        t_lo: dict[int, int] = {}
        t_hi: dict[int, int] = {}
        t_anchor: dict[int, int] = {}   # ko'chma blok oxiri (bo'lsa)
        # Ko'chma va oddiy paralar ALOHIDA — aralash yuklamali o'qituvchi
        # uchun kerakli kun sonini to'g'ri hisoblash uchun (quyida)
        t_need_f: defaultdict[int, int] = defaultdict(int)
        t_need_p: defaultdict[int, int] = defaultdict(int)

        for task in tasks:
            if task.teacher_id is None:
                continue
            days_ = [
                d for d in reg_day_list
                if task.group_start <= d <= task.group_end
                and (day_map.get((task.group_id, d)) is not None)
                and day_map[(task.group_id, d)].building_id in regional_building_ids_early
            ]
            if task.is_field:
                fd = field_days.get(task.group_id)
                if fd:
                    days_ = [d for d in days_ if d in fd]
            else:
                win = dept_window.get((task.group_id, task.department_id))
                if win:
                    days_ = [d for d in days_ if win[0] <= d <= win[1]]
            if not days_:
                continue
            tid = task.teacher_id
            t_need[tid] += task.paras_needed
            t_group_need[tid][task.group_id] += task.paras_needed
            lo_, hi_ = day_pos[days_[0]], day_pos[days_[-1]]
            t_lo[tid] = min(t_lo.get(tid, lo_), lo_)
            t_hi[tid] = max(t_hi.get(tid, hi_), hi_)
            (t_need_f if task.is_field else t_need_p)[tid] += task.paras_needed
            # Ko'chma bloki bor o'qituvchining bloki ko'chma oynasining
            # oxiriga bog'lanadi — aks holda uning oddiy darslari ko'chmadan
            # uzoqda qolib, viloyatga ikki marta borishga majbur bo'lardi.
            if task.is_field:
                t_anchor[tid] = max(t_anchor.get(tid, hi_), hi_)

        def _try_place(tid_, s_, e_):
            """[s_, e_] oynasiga o'qituvchining barcha paralari sig'adimi?

            Qaytaradi: (guruh sig'imining yangi qiymatlari, haqiqatan
            ishlatiladigan kunlar) yoki `None` (sig'masa).
            Simulyatsiya guruh sig'imini ham, o'qituvchining kunlik para
            chegarasini ham hisobga oladi.
            """
            rem = dict(t_group_need[tid_])
            new_caps: dict[tuple, int] = {}
            used_days: list[int] = []
            for i in range(s_, e_ + 1):
                if cap_left[i] <= 0:
                    continue   # shu kun to'lgan — o'qituvchi bu kunda ishlamaydi
                free_today = max_paras_per_day
                took = 0
                for g_ in list(rem):
                    if rem[g_] <= 0 or free_today <= 0:
                        continue
                    avail = new_caps.get((g_, i), group_cap_left.get((g_, i), 0))
                    take = min(avail, rem[g_], free_today)
                    if take > 0:
                        new_caps[(g_, i)] = avail - take
                        rem[g_] -= take
                        free_today -= take
                        took += take
                if took:
                    used_days.append(i)
            if any(v > 0 for v in rem.values()):
                return None
            return new_caps, used_days

        # ── TARTIB: DARSI KAM O'QITUVCHILAR BIRINCHI ────────────────────────
        # **Foydalanuvchi qoidasi**: "kam darsi bor o'qituvchilarni boshida
        # o'tib yuborish kerak".
        # **Nega to'g'ri (o'lchangan)**: avval "yuki katta birinchi" edi —
        # og'ir o'qituvchilar kalendarni bo'ylab egallab, kam darsli
        # o'qituvchilarga (2–3 kun kerak) KETMA-KET bo'sh kunlar qolmasdi va
        # aynan o'shalarda bo'sh kun chiqardi (S.U. Nazarov 9 para,
        # L. Salayeva 8 para, B. Nurboyev 8 para).
        # Og'ir o'qituvchi 18 kundan 8–12 tasini talab qiladi — uning bloki
        # baribir uzun va uzluksiz bo'lishga majbur, unga tanlov erkinligi
        # kerak emas. Kam darsli esa aniq 2–3 kunlik tirqish izlaydi.
        # (Xronologik tartib — faqat `t_lo` bo'yicha — ham sinaldi, yomonroq
        # chiqdi: 17/24 va 4 o'qituvchi bloksiz qoldi.)
        # ── ARALASH YUKLAMA: ko'chma + oddiy fan, BITTA UZLUKSIZ BLOK ───────
        # **Foydalanuvchi qoidasi**: "shunaqa o'qituvchilarning oddiy
        # darslarini va ko'chma darslarini ketma-ket qo'yish kerak — birinchi
        # oddiy darslarini o'tib olsa, keyin ko'chmani o'tsa, uzilish
        # bo'lmasin. Va shunaqa o'qituvchilarni birinchi joylashtirish kerak."
        #
        # Ikkita aniq o'zgarish:
        #  1) Ular greedy'da ENG BIRINCHI joylashtiriladi — blok ular uchun
        #     eng qiyin (ko'chma qismi davr oxiriga mixlangan, ya'ni tanlov
        #     erkinligi kam). Sig'im boshqalarga sarflanmasdan oldin ular
        #     eng qulay ketma-ket blokni oladi.
        #  2) Kerakli kun soni ALOHIDA hisoblanadi:
        #     `ceil(ko'chma/sig'im) + ceil(oddiy/sig'im)`.
        #     Umumiy `ceil(jami/sig'im)` NOTO'G'RI edi — ko'chma kunida
        #     o'qituvchi boshqa guruhlarga faqat 1- va 2-parada dars bera
        #     oladi, ya'ni ikki qism bir kunni to'liq baham ko'ra olmaydi.
        #     Real misol: `Sh.X. Isroilov` — 9 oddiy + 6 ko'chma = 15 para;
        #     umumiy formula 4 kun deydi, aslida 2 + 3 = 5 kun kerak.
        #     (Bu tuzatish AVVAL ALOHIDA sinalgan va yomonlashtirgan edi —
        #     chunki u paytda ular greedy'da OXIRIDA joylashtirilardi va
        #     kengroq oyna faqat sochilish erkinligini berardi. Birinchi
        #     joylashtirish bilan birga esa mantiqan to'g'ri ishlaydi.)
        mixed_first = {t for t in t_need if t_need_f.get(t) and t_need_p.get(t)}

        def _need_days(t):
            if t in mixed_first:
                return (max(1, -(-t_need_f[t] // max_paras_per_day))
                        + max(1, -(-t_need_p[t] // max_paras_per_day)))
            return max(1, -(-t_need[t] // max_paras_per_day))

        validated: set = set()   # sig'im tekshiruvidan o'tgan bloklar
        for tid in sorted(t_need, key=lambda t: (t not in mixed_first,
                                                 t_need[t], t_lo[t])):
            need_d = _need_days(tid)
            # **Sinalgan va RAD ETILGAN**: ko'chma+oddiy fani bor o'qituvchiga
            # `need_d + 1` berish (`Sh.X. Isroilov` — 15 para, formula 4 kun
            # deydi, amalda 5 kerak). Natija YOMONLASHDI: 23/24 dan 21–23 ga
            # tushdi va blok topilmaganlar 2 dan 3 ga oshdi — kengroq oyna
            # o'qituvchiga sochilish erkinligini beradi, ustiga guruh
            # sig'imini yeb, boshqa o'qituvchini blokdan siqib chiqaradi.
            lo_t, hi_t = t_lo[tid], t_hi[tid]
            # Zaxira: avval TOR oyna (aniq kerakli kun) sinaladi — u kunlik
            # limitni eng kam yeydi; sig'masa asta-sekin kengaytiriladi.
            # Hech biri sig'masa — o'qituvchi umuman cheklanmaydi (dars
            # yo'qolishidan ko'ra bo'sh kun afzal: "hech narsa yo'qolmasin"
            # eng ustuvor qoida).
            for slack in (0, 1, 2, 3):
                win_len = need_d + slack
                if win_len > hi_t - lo_t + 1:
                    continue
                if tid in t_anchor:
                    # ko'chma blok oxiriga bog'lash
                    starts = [max(lo_t, min(t_anchor[tid] - win_len + 1,
                                            hi_t - win_len + 1))]
                else:
                    starts = range(lo_t, hi_t - win_len + 2)
                for s in starts:
                    e = s + win_len - 1
                    if s < lo_t or e > hi_t:
                        continue
                    res_ = _try_place(tid, s, e)
                    if res_ is None:
                        continue
                    new_caps, used_days = res_
                    group_cap_left.update(new_caps)
                    # Kunlik o'qituvchi limiti FAQAT haqiqatan ishlatiladigan
                    # kunlarda kamayadi (butun oyna bo'ylab emas) — aks holda
                    # hisob ortiqcha ehtiyotkor bo'lib, oxirgi o'qituvchilarga
                    # joy qolmasdi (o'lchangan: 4 o'qituvchi oynasiz qolib,
                    # 9 ta dars yo'qolgan edi).
                    for i in used_days:
                        cap_left[i] -= 1
                    teacher_window[tid] = (reg_day_list[s], reg_day_list[e])
                    validated.add(tid)
                    break
                if tid in teacher_window:
                    break

            # **Sinalgan va RAD ETILGAN — "zaxira blok"**: blok topilmagan
            # o'qituvchilarga sig'im tekshiruvisiz taxminiy blok berish
            # (eng bo'sh joyni tanlab). Ikkala shaklda ham sinaldi:
            #   - qat'iy chegara bilan → 1274/1283 (9 ta DARS YO'QOLDI)
            #   - faqat yumshoq tortish bilan → 10–13 o'qituvchida bo'sh kun
            # Bloksiz qoldirish esa eng yaxshi natijani berdi (2–6). Sabab:
            # sifatsiz blok solverni NOTO'G'RI yo'naltiradi — u darslarni
            # o'sha blokka tortadi va o'qituvchining haqiqiy qulay kunlarini
            # buzadi. Shuning uchun blok topilmasa — hech qanday yo'naltirish
            # berilmaydi, faqat ogohlantirish chiqadi.

            if tid in validated:
                # ── QAT'IY CHEGARA — tor oynadan ±MARGIN kun kengroq ────────
                # **Nega ikki qatlam (o'lchangan)**:
                #   - faqat QAT'IY tor oyna: bo'sh kun 22/24 gacha yaxshilandi
                #     va o'qituvchi-kun nazariy minimumga (95) tushdi, LEKIN
                #     6–9 ta DARS YO'QOLDI (kalendar 355/360 to'la, erkinlik
                #     qolmaydi) — eng ustuvor qoidaning buzilishi.
                #   - faqat YUMSHOQ jazo: dars yo'qolmaydi, lekin bo'shliq
                #     18/24 da qolib ketdi — tortish kuchi yetmaydi.
                # Yechim: qidiruv maydonini qat'iy qisqartiramiz (±2 kun
                # zaxira bilan — CP-SAT'ga darslarni sig'dirish erkinligi
                # qoladi), tor oynaning O'ZIGA esa yumshoq jazo bilan
                # tortamiz.
                s_i = day_pos[teacher_window[tid][0]]
                e_i = day_pos[teacher_window[tid][1]]
                teacher_window_hard[tid] = (
                    reg_day_list[max(0, s_i - TEACHER_WINDOW_MARGIN)],
                    reg_day_list[min(len(reg_day_list) - 1,
                                     e_i + TEACHER_WINDOW_MARGIN)],
                )
            else:
                warnings.append(
                    f"O'qituvchi #{tid}: viloyatda ketma-ket kun bloki topilmadi "
                    f"(kerak {need_d} kun) — kunlik o'qituvchi limiti tor. "
                    "Bu o'qituvchida bo'sh kun qolishi mumkin."
                )

    _p(16, "Qoidalar tayyorlanmoqda",
       "Kafedra navbati, ko'chma mashg'ulot kunlari va o'qituvchilarning "
       "viloyatdagi ish kunlari oldindan hisoblanmoqda.")

    x = {}
    slot_building: dict[tuple, int | None] = {}
    window_violations = []   # oynadan tashqarida joylashgan viloyat darslari
    for ti, task in enumerate(tasks):
        # Vakant/o'qituvchisiz vazifada haqiqiy o'qituvchi yo'q — band vaqt
        # tekshiruvi qo'llanilmaydi (hech kim band bo'la olmaydi).
        busy = (
            _teacher_busy_set(task.teacher_id, date_from, date_to, all_paras)
            if task.teacher_id is not None else set()
        )

        for si, slot in enumerate(slots):
            # Faqat guruhning O'Z muddati ichidagi kunlar (har guruh alohida
            # boshlanish/tugash sanasiga ega bo'lishi mumkin — Group.start_date/end_date)
            if slot.date < task.group_start or slot.date > task.group_end:
                continue
            # Shu KUNGA tegishli haqiqiy smena/bino (guruh boshqa kunlarda boshqa
            # binoda bo'lishi mumkin — har bir sana alohida tekshiriladi)
            da = day_map.get((task.group_id, slot.date))
            if da is None:
                continue
            shift_para_ids = {p.id for p in all_paras if p.shift_id == da.shift_id}
            if slot.para_id not in shift_para_ids:
                continue
            # Oflayn guruhga bino shart — onlaynga (Zoom) kerak emas
            if not da.is_online and da.building_id is None:
                continue
            # O'qituvchi band bo'lsa o'tkazib yuborish
            if (slot.date, slot.para_id) in busy:
                continue
            # Viloyatda kafedra navbati — fan faqat o'z kafedrasiga ajratilgan
            # kunlar oynasida o'tilishi mumkin (yuqoridagi izohga qarang)
            outside_window = False
            if da.building_id in regional_building_ids_early:
                win = dept_window.get((task.group_id, task.department_id))
                if win and not (win[0] <= slot.date <= win[1]):
                    continue
                # O'qituvchining viloyatdagi ketma-ket kun bloki (yuqoriga
                # qarang). **QAT'IY EMAS** — blokdan tashqariga chiqish maqsad
                # funksiyasida katta vazn bilan jazolanadi.
                # **Nega qat'iy emas (o'lchangan)**: viloyat kalendari 355/360
                # to'la (guruhlarda atigi 5 slot zaxira). Qat'iy oyna bu
                # zichlikda CP-SAT'ga qolgan erkinlikni yo'q qilib, 6–9 ta
                # DARSNI YO'QOTDI — bu esa eng ustuvor qoidaning buzilishi.
                # Yumshoq yo'naltirish esa dars yo'qotmaydi (1-bosqich
                # jazosiz ishlaydi va `sum(x) >= best` bilan qulflanadi),
                # lekin viloyat bosqichlarida darslarni blokka tortadi —
                # bu solver uchun MAYDA, mahalliy yaxshilanish, ya'ni u
                # buni topa oladi (strukturani o'zi kashf qilishi shart emas).
                twh = teacher_window_hard.get(task.teacher_id)
                if twh and not (twh[0] <= slot.date <= twh[1]):
                    continue
                tw = teacher_window.get(task.teacher_id)
                outside_window = bool(tw) and not (tw[0] <= slot.date <= tw[1])
            # Ko'chma mashg'ulot kunlari guruh uchun BUTUNLAY ajratilgan
            # (yuqoridagi `field_days` izohiga qarang):
            #   - ko'chma fan FAQAT o'sha kunlarda o'tiladi
            #   - oddiy fanlar o'sha kunlarda UMUMAN o'tilmaydi
            # Ko'chma fan FAQAT ajratilgan oyna kunlarida (oyna zaxirali —
            # o'qituvchi to'qnashuvini hal qilish uchun). Oddiy fanlar bu
            # kunlarda TAQIQLANMAYDI — ular faqat ko'chma dars HAQIQATAN
            # tushgan kunlarda bloklanadi (quyida, `gf` cheklovi). Aks holda
            # zaxira kuni behuda band bo'lib, oddiy darslar yo'qolardi
            # (o'lchangan: 1283 dan 1267 ta joylashdi).
            if task.is_field:
                fdays = field_days.get(task.group_id)
                if fdays and slot.date not in fdays:
                    continue
            x[ti, si] = model.new_bool_var(f'x_{ti}_{si}')
            slot_building[ti, si] = da.building_id
            if outside_window:
                window_violations.append(x[ti, si])

    # ── HAFTALIK REJA: QAT'IY CHEKLOV EMAS, YUMSHOQ JAZO ─────────────────────
    # **Muhim (haqiqiy muammo, bosqichma-bosqich o'lchangan)**: haftalik reja
    # avval QAT'IY yuqori chegara (`sum(hafta) <= kvota`) sifatida qo'yilgan edi.
    # Kvotalar Python tomonida oldindan hisoblangani uchun ular real sig'im bilan
    # to'liq mos kelmasdi va natijada DARSLAR YO'QOLARDI (o'tilmagan dars =
    # qonun buzilishi). O'lchangan bosqichlar (1283 tadan):
    #   1161 — kvota faqat rejadagi haftalarga; guruh davri rejadan qisqa
    #          bo'lsa, o'sha haftaning soatlari umuman joylashmasdi
    #   1178 — ko'chirish (spillover) qo'shildi, lekin har fan uchun ALOHIDA
    #   1227 — ko'chirish guruh darajasida (fanlar hafta sig'imini baham ko'radi)
    #   1283 — QAT'IY kvota butunlay olib tashlandi (shu yechim)
    # 180 soniyalik limit ham 1227 dan nariga o'tmadi — demak muammo qidiruv
    # vaqtida emas, kvotaning O'ZIDA edi.
    #
    # Yangi yondashuv: haftalik reja — **afzallik**, majburiyat emas.
    #   - Constraint 1 (umumiy son) qat'iyligicha qoladi: har fan `paras_needed`
    #     dan oshmaydi, va 1-bosqich maqsadi uni MAKSIMAL qiladi
    #   - Rejadan chetlanish (`over[ti][wi]` — rejadagi kvotadan ortiqcha
    #     qo'yilgan para soni) 2-bosqich maqsad funksiyasida jazolanadi
    # Shunday qilib solver darsni "o'z haftasiga" qo'yishga intiladi, lekin
    # sig'im yetmasa uni TASHLAB YUBORMAY, qo'shni haftaga suradi.
    task_week_slots: list[dict] = []
    for ti in range(len(tasks)):
        wsc: defaultdict[int, int] = defaultdict(int)
        for si in range(len(slots)):
            if (ti, si) in x:
                wsc[_week_index(slots[si].date, tasks[ti].group_start)] += 1
        task_week_slots.append(dict(wsc))

    # Rejadan chetlanish o'zgaruvchilari (2-bosqich jazosi uchun)
    week_dev_vars = []
    for ti, task in enumerate(tasks):
        if not any(w > 0 for w in task.week_hours):
            continue  # haftalik rejasi yo'q — chetlanish tushunchasi qo'llanmaydi
        for wi, slot_cnt in task_week_slots[ti].items():
            quota = (task.week_hours[wi] or 0) // 2 if wi < len(task.week_hours) else 0
            if quota >= slot_cnt:
                continue  # bu haftada kvotadan oshib ketish imkoni yo'q
            week_vars = [
                x[ti, si] for si in range(len(slots))
                if (ti, si) in x
                and _week_index(slots[si].date, task.group_start) == wi
            ]
            if not week_vars:
                continue
            dev = model.new_int_var(0, slot_cnt, f'dev_{ti}_{wi}')
            model.add(dev >= sum(week_vars) - quota)
            week_dev_vars.append((ti, dev))

    # ── CONSTRAINT 1: Har vazifa kerakli para sonidan OSHMASLIGI shart ────────
    # **Muhim**: qat'iy tenglik (`==`) emas, yuqori chegara (`<=`) — chunki bir
    # nechta fan (bitta guruh, ko'pincha bitta o'qituvchi) bir vaqtda cheklangan
    # slot pulidan foydalanadi (Constraint 2/3 — bitta guruh/o'qituvchi bir
    # vaqtda faqat bitta darsda bo'lishi mumkin). Agar ularning YIG'INDI talabi
    # fizik sig'imdan oshsa (masalan qisqa muddatli guruh + og'ir haftalik yuk),
    # qat'iy tenglik butun modelni (BARCHA guruhlar uchun, `x` bitta umumiy
    # modelda baham ko'rilgani sababli) INFEASIBLE qilib qo'yardi (haqiqiy bug,
    # tuzatilgan). `<=` + quyidagi `model.maximize(sum(x.values()))` maqsadi
    # birgalikda "iloji boricha ko'p joylashtirish" natijasini beradi — yetarli
    # joy bo'lganda avvalgidek to'liq, yetmasa qisman.
    for ti, task in enumerate(tasks):
        vars_ = [x[ti, si] for si in range(len(slots)) if (ti, si) in x]
        if not vars_:
            warnings.append(
                f"Vazifa (teacher={task.teacher_id}, group={task.group_id}) "
                f"uchun mos slot topilmadi — o'tkazib yuborildi."
            )
            continue

        # Yagona miqdoriy chegara — o'quv rejadagi HAQIQIY talab
        # (`auditorium_hours // 2`). Haftalar bo'yicha taqsimot endi qat'iy
        # cheklov emas (yuqoriga qarang), shuning uchun bu yerda faqat umumiy
        # son cheklanadi va 1-bosqich maqsadi uni maksimallashtiradi.
        required = min(task.paras_needed, len(vars_))
        if required < task.paras_needed:
            warnings.append(
                f"Vazifa (teacher={task.teacher_id}, group={task.group_id}) uchun "
                f"yetarli slot yo'q ({task.paras_needed} kerak, {required} joy bor) — "
                "qisman joylashtirildi."
            )
        model.add(sum(vars_) <= required)

    # ── CONSTRAINT 2: O'qituvchi bir vaqtda faqat bir joyda ──────────────────
    # **Muhim (haqiqiy bug, tuzatilgan)**: avval `si` (slot indeksi, `para_id`
    # orqali) bo'yicha guruhlangan edi — lekin `para_id` faqat BITTA smenaga
    # tegishli, turli guruhlar turli smenalarda bo'lishi mumkin. Agar ikkita
    # turli smenaning paralari bir xil aniq vaqtga to'g'ri kelsa (masalan
    # ikkalasida ham "1-para" 09:00-10:20), ular turli `para_id`ga ega bo'lgani
    # uchun avvalgi kod ularni "boshqa-boshqa slot" deb hisoblab, BIR XIL
    # o'qituvchini ikkala guruhga bir vaqtda qo'yib yuborishi mumkin edi
    # (production'da haqiqatan sodir bo'lgan, tekshirilgan). Endi haqiqiy
    # (sana, boshlanish vaqti, tugash vaqti) bo'yicha guruhlanadi — shunda
    # turli smenalarning bir xil vaqtga to'g'ri keluvchi paralari ham to'g'ri
    # to'qnashuv sifatida aniqlanadi.
    teacher_slot: defaultdict[tuple, list] = defaultdict(list)
    for (ti, si), var in x.items():
        # Vakant/o'qituvchisiz vazifalarda haqiqiy odam yo'q — ular bir-biriga
        # (yoki hech kimga) "to'qnashuv" hosil qilmaydi, shuning uchun bu
        # cheklovga umuman kiritilmaydi.
        if tasks[ti].teacher_id is None:
            continue
        slot = slots[si]
        para = para_by_id[slot.para_id]
        time_key = (slot.date, para.start_time, para.end_time)
        teacher_slot[(tasks[ti].teacher_id, time_key)].append(var)

    for vars_ in teacher_slot.values():
        if len(vars_) > 1:
            model.add(sum(vars_) <= 1)

    # ── CONSTRAINT 2c: O'QITUVCHINING KUNIDA TESHIK BO'LMASIN ────────────────
    # **Foydalanuvchi qoidasi**: "O'qituvchi uchun maksimal bo'sh kun va bo'sh
    # para qoldirilmasligi kerak."
    #
    # **Haqiqiy bug**: `Constraint 5` kun ichida teshikni faqat GURUH uchun
    # taqiqlardi. O'qituvchi esa I-parada dars berib, II-parani bo'sh o'tkazib,
    # III-parada yana darsga kirishi mumkin edi — real jadvalda (#52) o'lchandi:
    # **73/559 o'qituvchi-kun (13%) teshikli** (63 tasida 1 para, 10 tasida
    # 2 para bo'shliq). O'qituvchi uchun bu eng noqulay holat — u kelib,
    # kutib o'tirishi kerak.
    #
    # Formulasi ATAYLAB yangi o'zgaruvchisiz: `Constraint 2` allaqachon
    # kafolatlaydiki har bir (o'qituvchi, vaqt) uchun `sum(vars) <= 1`, ya'ni
    # bu yig'indi 0/1 IFODA — alohida bool kerak emas. Uchlik uchun taqiq:
    #     S_i + S_k - S_j <= 1      (i < j < k, vaqt bo'yicha tartibda)
    # ya'ni "birinchi va uchinchida bor, o'rtada yo'q" holati imkonsiz.
    # Kunda para soni kam (3–4), shuning uchun uchliklar soni ham kichik.
    #
    # MUHIM: yangi o'zgaruvchi qo'shish 1-bosqichni sekinlashtirib darslarni
    # yo'qotishi o'lchangan (yuqoridagi `tg_day_single` tarixiga qarang) —
    # shuning uchun bu yerda faqat mavjud `x` lar ustidan chiziqli cheklov.
    # **FAQAT VILOYAT binolarida** (foydalanuvchi bilan aniqlashtirilgan:
    # "faqat viloyatda o'qituvchi uchun maksimal bo'sh kun va bo'sh para
    # qoldirilmasligi kerak"). Markazda o'qituvchi o'z shahrida yashaydi va
    # u yerda HAFTALIK REJA ustun turadi — kun ichidagi bo'shliqni taqiqlash
    # rejaga qarshi ishlab, darslarni yo'qotardi (o'lchangan: butun tashkilotga
    # qo'llanganda 1283 -> 1282).
    # `Constraint 2b` bir kunda faqat bitta bino kafolatlaydi, shuning uchun
    # o'sha kuni o'qituvchi markazda bo'lsa, quyidagi viloyat o'zgaruvchilari
    # baribir 0 bo'ladi va cheklov o'z-o'zidan bajariladi.
    regional_building_ids = set(
        Building.objects.filter(organization=organization, is_regional=True)
        .values_list('id', flat=True)
    )
    teacher_day_times: defaultdict[tuple, defaultdict] = defaultdict(
        lambda: defaultdict(list))
    for (ti, si), var in x.items():
        if tasks[ti].teacher_id is None:
            continue
        if slot_building.get((ti, si)) not in regional_building_ids:
            continue
        slot = slots[si]
        para = para_by_id[slot.para_id]
        teacher_day_times[(tasks[ti].teacher_id, slot.date)][
            para.start_time].append(var)

    for by_time in (teacher_day_times.values()
                    if REGIONAL_NO_GAP_WITHIN_DAY else ()):
        times = sorted(by_time)
        if len(times) < 3:
            continue
        for a in range(len(times)):
            for b in range(a + 1, len(times) - 1):
                for c in range(b + 1, len(times)):
                    model.add(sum(by_time[times[a]]) + sum(by_time[times[c]])
                              - sum(by_time[times[b]]) <= 1)

    # ── CONSTRAINT 2b: O'qituvchi BIR KUNDA faqat BITTA binoda ───────────────
    # **Foydalanuvchi qoidasi 2.1**: "Hech qachon bir o'qituvchiga 2 ta binoda
    # darsni ketma-ket paraga qo'yish mumkin emas. Bitta binoda darsda bo'lgan
    # o'qituvchi o'sha kuni boshqa binoda darsda bo'lmasligi kerak."
    #
    # **Haqiqiy bug**: Constraint 2 faqat bir XIL VAQTdagi to'qnashuvni
    # taqiqlardi — ya'ni o'qituvchini ertalab bir binoda, tushdan keyin
    # (ayniqsa keyingi parada) butunlay boshqa binoda darsga qo'yish mumkin
    # edi. Binolar orasida yo'l vaqti bor (viloyat binosi — boshqa shaharda),
    # bu jismonan bajarib bo'lmaydigan jadval demakdir.
    #
    # Onlayn (Zoom) darslar bu cheklovga KIRMAYDI — ular joyga bog'liq emas
    # (`building_id is None`), o'qituvchi qayerda bo'lsa ham o'ta oladi.
    teacher_day_building: defaultdict[tuple, dict] = defaultdict(dict)
    for (ti, si), var in x.items():
        t_id = tasks[ti].teacher_id
        if t_id is None:
            continue
        b_id = slot_building.get((ti, si))
        if b_id is None:
            continue
        teacher_day_building[(t_id, slots[si].date)].setdefault(b_id, []).append(var)

    for (t_id, d_), by_building in teacher_day_building.items():
        if len(by_building) < 2:
            continue   # shu kuni faqat bitta bino — cheklov kerak emas
        flags = []
        for b_id, vars_ in by_building.items():
            bvar = model.new_bool_var(f'tb_{t_id}_{d_}_{b_id}')
            for v in vars_:
                model.add_implication(v, bvar)
            flags.append(bvar)
        model.add(sum(flags) <= 1)

    # ── CONSTRAINT 3: Guruh bir vaqtda faqat bir darsda ──────────────────────
    group_slot: defaultdict[tuple, list] = defaultdict(list)
    for (ti, si), var in x.items():
        group_slot[(tasks[ti].group_id, si)].append(var)

    for vars_ in group_slot.values():
        if len(vars_) > 1:
            model.add(sum(vars_) <= 1)

    # ── CONSTRAINT 4: Haftalik soat taqsimoti — YUMSHOQ (jazo orqali) ────────
    # Qat'iy cheklov sifatida OLIB TASHLANDI: u darslarni yo'qotayotgan edi
    # (yuqoridagi "HAFTALIK REJA" izohiga qarang — 1283 tadan 1227 tasi
    # joylashardi). Endi rejadan chetlanish `week_dev_vars` orqali o'lchanadi
    # va 2-bosqich maqsad funksiyasida jazolanadi: solver darsni "o'z haftasiga"
    # qo'yishga intiladi, lekin sig'im yetmasa uni tashlab yubormay, qo'shni
    # haftaga suradi. Har bir guruhning "1-hafta"si o'zining `group_start`idan
    # hisoblanadi (global oy boshidan emas — haqiqiy bug, tuzatilgan).

    # ── CONSTRAINT 5: Kun ichida "teshik" bo'lmasligi (paralar ketma-ket) ─────
    # Talab: "kuniga necha para belgilangan bo'lsa shuncha para qo'yilishi shart".
    # Amalda darslar soni o'quv reja soatlari bilan chegaralangan (hamma kunni
    # to'ldirishga har doim yetmasligi mumkin), shuning uchun ikki qismli yechim:
    #   (a) shu yerda — QAT'IY cheklov: kun ichidagi paralar 1-paradan boshlab
    #       ketma-ket to'ldiriladi, o'rtada bo'sh para qolmaydi
    #       (`y[k+1] <= y[k]`, para `order` bo'yicha)
    #   (b) maqsad funksiyasida — ishlatilgan (guruh, kun) juftliklari jazolanadi,
    #       shunda darslar kam kunga ZICH joylashadi (ya'ni ishlatilgan kunlar
    #       to'la bo'ladi), yarim-yarim ko'p kunga sochilib ketmaydi.
    # Bu qat'iy cheklov modelni INFEASIBLE qilib qo'ya olmaydi — u faqat qaysi
    # paraga qo'yishni cheklaydi, darslar sonini emas (barcha miqdor cheklovlari
    # `<=` bo'lib qolaveradi).
    #
    # `group_day_used[(group_id, date)]` — shu kunda guruhda dars bor-yo'qligini
    # bildiruvchi bool (maqsad funksiyasi uchun ham ishlatiladi).
    slots_by_group_day: defaultdict[tuple, dict] = defaultdict(dict)
    for (ti, si), var in x.items():
        slot = slots[si]
        key = (tasks[ti].group_id, slot.date)
        slots_by_group_day[key].setdefault(slot.para_id, []).append(var)

    group_day_used: dict[tuple, object] = {}
    for key, para_vars in slots_by_group_day.items():
        # Para `order` bo'yicha tartiblash — `para_id` tartibi ishonchli emas
        ordered = sorted(para_vars.items(), key=lambda kv: para_by_id[kv[0]].order)
        y_list = []
        for pid, vars_ in ordered:
            # y = shu parada guruhda dars bormi (Constraint 3 bo'yicha ko'pi bilan 1 ta)
            y = model.new_bool_var(f'y_{key[0]}_{key[1]}_{pid}')
            model.add(sum(vars_) == y)
            y_list.append(y)
        # Teshik yo'q: keyingi para faqat oldingisi to'lgan bo'lsa band bo'ladi
        for i in range(len(y_list) - 1):
            model.add(y_list[i + 1] <= y_list[i])
        if y_list:
            # Kun ishlatilgan = birinchi para band (ketma-ketlik tufayli ekvivalent)
            group_day_used[key] = y_list[0]

    # ── PARCHALANISHGA QARSHI ────────────────────────────────────────────────
    # Qo'lda tuzilgan haqiqiy jadval (`iyun.xlsx`) bilan o'lchab solishtirilgan:
    #
    #   o'qituvchi bir guruhga kirsa nechta para o'tadi:
    #                        qo'lda    dastur (tuzatishdan oldin)
    #        1 para           45%   →   56%    ← juda parchalangan
    #        2 para           40%   →   31%
    #        ketma-ket        99%   →   82%
    #   guruh kunining naqshi:
    #        "2+2"            32%   →    6%    ← deyarli yo'qolgan
    #        "1+1+1+1"         8%   →   30%    ← 4 barobar ko'p
    #        "4"               3%   →   10%    ← zerikarli
    #
    # Ya'ni tinglovchi kuniga 2 ta o'qituvchi o'rniga 4 ta har xil o'qituvchini
    # ko'radi. Maqsad — 2 paralik blok (qo'lda tuzilgan jadvaldagi ustun naqsh).
    #
    # Ikki tomonlama yondashuv, chunki faqat bittasi yetarli emas:
    #   (a) QAT'IY yuqori chegara — bitta fan bir kunda butun kunni egallamasin
    #       (foydalanuvchi: "bitta o'qituvchi 4 ta parani bitta fanda o'tishi
    #       yaxshi emas, zerikarli bo'lib qoladi")
    #   (b) YUMSHOQ jazo — (o'qituvchi, guruh, kun) uchliklari soni kamaysin.
    #       Bu 1+1+1+1 (4 ta uchlik) o'rniga 2+2 (2 ta uchlik) ni afzal qiladi.
    #       (a) siz bu 4+0 ga (1 ta uchlik) surib yuborardi — shuning uchun
    #       ikkalasi BIRGA ishlatiladi.
    SUBJECT_DAY_MAX_PARA = 3

    subj_day_vars: defaultdict[tuple, list] = defaultdict(list)
    tg_day_vars: defaultdict[tuple, list] = defaultdict(list)
    tg_day_tasks: defaultdict[tuple, set] = defaultdict(set)
    for (ti, si), var in x.items():
        t = tasks[ti]
        d = slots[si].date
        subj_day_vars[(t.group_id, t.subject_id, d)].append(var)
        if t.teacher_id:
            tg_day_vars[(t.teacher_id, t.group_id, d)].append(var)
            tg_day_tasks[(t.teacher_id, t.group_id, d)].add(ti)

    for vars_ in subj_day_vars.values():
        if len(vars_) > SUBJECT_DAY_MAX_PARA:
            model.add(sum(vars_) <= SUBJECT_DAY_MAX_PARA)

    # (o'qituvchi, guruh, kun) bandligi — MARKAZ bosqichida jazolanadi.
    # MUHIM: ikkala yo'nalish ham bog'lanadi. Faqat `var -> b` bo'lsa, solver
    # darsi YO'Q uchliklarga ham b=1 qo'yib, jazoni "aldab" o'tishi mumkin
    # (bu loyihada `gf` va `presence` bilan ikki marta uchragan haqiqiy xato).
    #
    # ── SINALGAN VA RAD ETILGAN: "kelgan o'qituvchi kamida 2 para o'tsin" ────
    # QAT'IY cheklov sifatida sinaldi (`sum(paralar) >= 2 * b`, ya'ni 0 yoki
    # >=2), o'qituvchining shu guruhdagi umumiy yuki >=2 bo'lgan holatlarda.
    # Natija (420s, real dump): **1201/1283 — 82 ta DARS YO'QOLDI**.
    #
    # Sabab STRUKTURAVIY va muhim: bu ma'lumotdagi smenalarning ko'pchiligi
    # 3 PARALI ("Kunduzgi" va "Kechki" — 3 para, faqat "Kunduzgi 4 Para
    # Ertalab" 4 parali). 3 paralik kunda "har bir o'qituvchi >= 2 para"
    # degani amalda "kuniga faqat BITTA o'qituvchi" degani (2+2=4 > 3).
    # O'lchov buni tasdiqladi: "3" naqshi 61% ga sakradi, ya'ni bitta
    # o'qituvchi butun kunni egallab oldi — bu esa foydalanuvchi ataylab
    # istamagan holat ("zerikarli bo'lib qoladi").
    #
    # MUHIM XULOSA: qo'lda tuzilgan jadval bilan "2+2" naqshi bo'yicha
    # solishtirish NOTO'G'RI edi — u 4 PARALI kunlarga qurilgan (iyun.xlsx da
    # barcha kunlar 4 para). 3 paralik kunda "2+2" umuman mumkin emas; u
    # yerdagi eng yaxshi naqsh — "2+1" yoki "3". Shuning uchun maqsad
    # "1+1+1" ni "2+1" ga aylantirish bo'lishi kerak, "2+2" ga emas.
    # `tg_day_bools` — kalit bo'yicha saqlanadi, chunki jazo VILOYAT va MARKAZ
    # bosqichlariga ALOHIDA bo'linadi (viloyat vazifalari `regional_tasks`
    # quyida hisoblanadi, shuning uchun ajratish maqsad funksiyasida bo'ladi).
    teacher_group_day_bools = []
    tg_day_bools: dict[tuple, object] = {}
    # ── SINALGAN VA RAD ETILGAN: "aynan 1 paralik blok" jazosi ───────────────
    # Nishonga aniqroq olingan jazo yozishga ikki marta urinildi — blok AYNAN
    # 1 para bo'lsa jazolanadi (2 va 3 orasida farq qo'ymay, ya'ni 2 dan 3 ga
    # surish uchun rag'bat bermay). Ikkala shakl ham RAD ETILDI, chunki
    # ikkalasi ham modelga YANGI O'ZGARUVCHI qo'shadi va shu bilan
    # **1-BOSQICHNI** (maksimal dars soni) sekinlashtiradi:
    #   (a) reifikatsiya (`sum == 1` <-> bool): 1-bosqich 40s -> 110s,
    #       viloyat bosqichlariga vaqt qolmay bo'sh kunsizlik 10/24 ga tushdi
    #   (b) chiziqli `pair` bool (`2*pr <= sum(vars_)`, jazo = `b - pr`):
    #       1-bosqich 120s limitiga yetdi va **1273/1283 — 10 ta dars yo'qoldi**
    # 1-bosqich eng ustuvor qoidani (hech bir dars yo'qolmasin) ta'minlaydi va
    # modelning har qanday kengayishiga sezgir. Shuning uchun parchalanish
    # jazosi FAQAT allaqachon mavjud `tg_day_bools` orqali beriladi — yangi
    # o'zgaruvchi qo'shilmaydi.
    for key, vars_ in tg_day_vars.items():
        b = model.new_bool_var(f'tgd_{key[0]}_{key[1]}_{key[2]}')
        for v in vars_:
            model.add_implication(v, b)
        model.add(b <= sum(vars_))
        teacher_group_day_bools.append(b)
        tg_day_bools[key] = b

    # ── VILOYAT BINOLARI: komandirovkani minimallashtirish ────────────────────
    # `Building.is_regional=True` binolarga o'qituvchilar KOMANDIROVKAGA yuboriladi.
    # Foydalanuvchi belgilagan chekinib bo'lmaydigan qoidalar:
    #   1) O'qituvchi kelsa — fanini OXIRIGACHA ketma-ket o'tib ketsin, keyin
    #      keyingi o'qituvchi kelsin (fanlar bir-biriga aralashib ketmasin)
    #   2) Bir vaqtda viloyatda MAKSIMAL KAM o'qituvchi bo'lsin
    #   3) Har bir o'qituvchi uchun viloyatdagi KUN soni maksimal kam bo'lsin
    # Buning evaziga haftalik reja chetlanishi viloyatda maqbul (foydalanuvchi
    # bilan aniqlashtirilgan) — shuning uchun quyida viloyat vazifalari uchun
    # `week_dev` jazosi ancha past vazn bilan hisoblanadi.
    presence_vars = []        # (o'qituvchi, kun) — komandirovka kunlari
    trip_vars = []            # (o'qituvchi, hafta) — alohida safarlar soni
    task_day_vars = []        # (vazifa, kun) — fan nechta kunga yoyilgan
    span_terms = []           # (vazifa) — birinchi va oxirgi kun orasidagi masofa
    teacher_gap_terms = []    # (o'qituvchi) — viloyatdagi bo'sh kunlar soni
    teacher_gap_hard_terms = []   # eng ko'p darsli o'qituvchilarda 1 kundan ortiq bo'shliq
    dept_spread_terms = []    # (kafedra) — kafedra bloki qancha yoyilgan
    dept_order_terms = []     # (kafedra juftligi) — Department.order tartibi buzilishi
    regional_tasks: set[int] = set()

    if regional_building_ids:
        regional_teacher_day: defaultdict[tuple, list] = defaultdict(list)
        regional_teacher_week: defaultdict[tuple, list] = defaultdict(list)
        regional_task_day: defaultdict[tuple, list] = defaultdict(list)
        for (ti, si), var in x.items():
            if slot_building.get((ti, si)) not in regional_building_ids:
                continue
            regional_tasks.add(ti)
            slot = slots[si]
            # Fan (vazifa) darajasidagi kun — vakant fanlar uchun ham kerak
            # (ular ham guruhning kunini band qiladi va aralashib ketmasligi lozim)
            regional_task_day[(ti, slot.date)].append(var)
            t_id = tasks[ti].teacher_id
            if t_id is None:
                continue  # vakant — haqiqiy odam yo'q, komandirovka ham yo'q
            regional_teacher_day[(t_id, slot.date)].append(var)
            regional_teacher_week[
                (t_id, _week_index(slot.date, date_from))
            ].append(var)

        def _presence(prefix, mapping, out):
            """Har kalit uchun bitta bool: shu (o'qituvchi/vazifa, ...) da dars bormi.

            **Teskari bog'lanish (`p <= sum(vars)`) SHART** — haqiqiy bug,
            tuzatilgan. Faqat `v -> p` bo'lganda `p` "dars bor" degani emas,
            balki "dars bo'lishi MUMKIN" degani bo'lib qolardi: solver uni
            darsi YO'Q kunlarga ham 1 qilib qo'yishi mumkin edi. Bu ayniqsa
            bo'sh kunlar formulasini (`gap = oxirgi - birinchi + 1 - sum(p)`)
            buzardi — u yerda `sum(p)` AYIRILADI, ya'ni soxta `p=1` bo'shliqni
            sun'iy ravishda kichraytirib ko'rsatardi. Hisob: soxta kun +150
            (presence jazosi), lekin −100 (gap) −400 (og'ir o'qituvchi
            ortiqchasi) → solver uchun ALDASH foydali edi, natijada o'lchangan
            "bo'sh kun" ko'rsatkichi haqiqatga mos kelmasdi.
            """
            made = {}
            for key, vars_ in mapping.items():
                p = model.new_bool_var(f'{prefix}_{key}')
                for v in vars_:
                    model.add_implication(v, p)
                model.add(p <= sum(vars_))
                out.append(p)
                made[key] = p
            return made

        teacher_day_bool = _presence('present', regional_teacher_day, presence_vars)
        _presence('trip', regional_teacher_week, trip_vars)
        task_day_bool = _presence('tday', regional_task_day, task_day_vars)

        # ── QAT'IY: viloyatga kelgan o'qituvchi kuniga KAMIDA 2 PARA o'tsin ──
        # **Foydalanuvchi qoidasi**: "bir kunda o'qituvchi faqat 1 para
        # o'tishiga mumkin bo'lmasligi kerak, 2+ paralar bo'lishi shart".
        # Mantiq: viloyatga komandirovkaga borish uchun 1 para arzimaydi.
        #
        # `teacher_day_bool` ikki tomonlama bog'langan (yuqoridagi `_presence`
        # izohiga qarang), ya'ni `p = 1` AYNAN "shu kuni dars bor" degani.
        # Shuning uchun `sum(vars) >= 2 * p` — yangi o'zgaruvchisiz aniq
        # "0 yoki 2+" shartini beradi.
        #
        # DIQQAT — bu (o'qituvchi, KUN) darajasida, `(o'qituvchi, GURUH, kun)`
        # darajasida EMAS. Ikkinchisi avval sinalgan va **82 ta dars
        # yo'qotgan** edi (3 paralik smenada "har guruhga >= 2 para" amalda
        # "kuniga bitta guruh" degani bo'lib qolardi). Bu yerdagi shakl
        # yumshoqroq: o'qituvchi ikki guruhga 1 paradan bersa ham shart
        # bajariladi.
        if REGIONAL_MIN_PARAS_PER_DAY > 1:
            for key, p in teacher_day_bool.items():
                vars_ = regional_teacher_day[key]
                if len(vars_) >= REGIONAL_MIN_PARAS_PER_DAY:
                    model.add(sum(vars_) >= REGIONAL_MIN_PARAS_PER_DAY * p)

        # ── QAT'IY: bir kunda viloyatda ko'pi bilan (guruh soni + 2) o'qituvchi ──
        # **Foydalanuvchi qoidasi 2**: "maksimal nechta guruh bo'lsa faqat n+2 ta
        # o'qituvchi viloyatda bo'lishi mumkin". Guruhlar soni har kun uchun
        # `GroupDayAssignment`dan aniq ma'lum (o'zgarmas son), shuning uchun bu
        # oddiy chiziqli cheklov.
        # Bu qoida o'qituvchini kunига BIR guruhga emas, iloji boricha bir
        # nechta guruhga ketma-ket dars berishga majbur qiladi — komandirovkaga
        # borgan odam sonini keskin kamaytiradi.
        # O'lchangan boshlang'ich holat: 5 guruh (limit 7), lekin 18 kundan
        # 10 tasida 8–9 o'qituvchi bor edi.
        groups_per_reg_day: defaultdict[object, set] = defaultdict(set)
        for (gid_, d_), da_ in day_map.items():
            if da_.building_id in regional_building_ids:
                groups_per_reg_day[d_].add(gid_)

        by_day: defaultdict[object, list] = defaultdict(list)
        for (t_id_, d_), p_ in teacher_day_bool.items():
            by_day[d_].append(p_)
        for d_, flags in by_day.items():
            limit = len(groups_per_reg_day.get(d_, ())) + REGIONAL_TEACHER_SLACK
            if 0 < limit < len(flags):
                model.add(sum(flags) <= limit)

        # ── FANNI KETMA-KET TUGATISH (span) ──────────────────────────────────
        # Yuqoridagi `task_day_vars` fan nechta KUNGA yoyilganini kamaytiradi,
        # lekin o'zi kunlarning YONMA-YON bo'lishini kafolatlamaydi (masalan
        # 2 kun: 3-sentabr va 25-sentabr). Shuning uchun har bir viloyat
        # vazifasi uchun "span" — birinchi va oxirgi dars kuni orasidagi masofa —
        # ham jazolanadi. Ikkalasi birga: fan minimal sonli, YONMA-YON kunlarda
        # o'tib tugaydi, ya'ni o'qituvchi bir kelib fanini yopib ketadi.
        day_index = {d: i for i, d in enumerate(sorted({s_.date for s_ in slots}))}
        task_days: defaultdict[int, list] = defaultdict(list)
        for (ti, d), p in task_day_bool.items():
            task_days[ti].append((day_index[d], p))
        for ti, pairs in task_days.items():
            if len(pairs) < 2:
                continue
            idxs = [i for i, _ in pairs]
            lo, hi = min(idxs), max(idxs)
            first = model.new_int_var(lo, hi, f'first_{ti}')
            last = model.new_int_var(lo, hi, f'last_{ti}')
            for i, p in pairs:
                model.add(first <= i).only_enforce_if(p)
                model.add(last >= i).only_enforce_if(p)
            span = model.new_int_var(0, hi - lo, f'span_{ti}')
            model.add(span == last - first)
            span_terms.append(span)

        # ── O'QITUVCHI UZLUKSIZLIGI: viloyatda bo'sh kun qolmasin ────────────
        # Foydalanuvchi talabi: "o'qituvchi biror kun ham bo'sh qolmasdan hamma
        # darsini o'tishi kerak" — ya'ni komandirovkaga borgan o'qituvchining
        # viloyatdagi kunlari YONMA-YON bo'lishi kerak (borib-kelib yurmasin).
        # `teacher_gap = span - kunlar_soni` — 0 bo'lsa mukammal uzluksiz.
        # Talab BARCHA o'qituvchilarga qo'llanadi (avval faqat "eng ko'p darsi
        # bor" o'qituvchilar uchun edi — foydalanuvchi keyinchalik buni
        # kengaytirdi: "o'qituvchi borgandan keyin bo'sh kun qolishi mumkin
        # emas").
        teacher_days_map: defaultdict[int, list] = defaultdict(list)
        for (t_id, d), p in teacher_day_bool.items():
            teacher_days_map[t_id].append((day_index[d], p))
        for t_id, pairs in teacher_days_map.items():
            if len(pairs) < 2:
                continue
            idxs = [i for i, _ in pairs]
            lo, hi = min(idxs), max(idxs)
            tf = model.new_int_var(lo, hi, f'tfirst_{t_id}')
            tl = model.new_int_var(lo, hi, f'tlast_{t_id}')
            for i, p in pairs:
                model.add(tf <= i).only_enforce_if(p)
                model.add(tl >= i).only_enforce_if(p)
            # Bo'sh kunlar soni = (oxirgi - birinchi + 1) - haqiqiy kunlar
            gap = model.new_int_var(0, hi - lo, f'tgap_{t_id}')
            model.add(gap == tl - tf + 1 - sum(p for _, p in pairs))
            teacher_gap_terms.append(gap)

            # ── "BO'SH KUN QOLISHI MUMKIN EMAS" (foydalanuvchi qoidasi 3) ────
            # Talab: "o'qituvchi borgandan keyin bo'sh kun qolishi mumkin
            # emas" — ya'ni `gap == 0`, BARCHA o'qituvchilar uchun.
            #
            # **Nega to'g'ridan-to'g'ri `model.add(gap == 0)` EMAS**: o'qituvchi
            # bir nechta guruhda dars beradi va guruhlarning viloyat kunlari
            # bir-biridan uzoq bo'lishi mumkin — bunday holda qat'iy cheklov
            # butun modelni INFEASIBLE qilib, HECH QANDAY jadval chiqmay
            # qolardi (bu loyihada bir necha marta uchragan xato turi).
            # Yechim — indikator literal: `gap == 0` faqat `ok` rost bo'lganda
            # majburlanadi, `ok` yolg'onligi esa maqsad funksiyasida JUDA
            # katta vazn bilan jazolanadi. Amalda bu qat'iy cheklov bilan bir
            # xil natija beradi (solver iloji bo'lsa har doim `ok=1` qiladi),
            # lekin strukturaviy imkonsiz holatda jadvalni yo'qotmaydi —
            # o'sha o'qituvchi ogohlantirish bilan istisno bo'lib qoladi.
            ok = model.new_bool_var(f'tgap0_{t_id}')
            model.add(gap == 0).only_enforce_if(ok)
            teacher_gap_hard_terms.append(~ok)

        # ── KAFEDRA NAVBATI (Department.order bo'yicha) ──────────────────────
        # Foydalanuvchi talabi: viloyatda avval BITTA kafedraning o'qituvchilari
        # borib fanlarini o'tib tugatsin, keyin KEYINGI kafedra chiqsin —
        # kafedralar aralashib ketmasin, `Department.order` tartibida navbatma-navbat.
        #
        # Modellashtirish: har kafedra uchun viloyatdagi birinchi/oxirgi kun
        # (`dfirst`/`dlast`). Ikkita jazo:
        #   1) kafedra ichidagi tarqoqlik (`dlast - dfirst`) — bir kafedra
        #      ixcham blokda ishlasin
        #   2) tartib buzilishi — `order` bo'yicha keyingi kafedra oldingisi
        #      tugagandan KEYIN boshlansin (`overlap = dlast[oldingi] - dfirst[keyingi]`)
        # Ikkalasi ham YUMSHOQ (jazo), qat'iy emas — aks holda sig'im yetmagan
        # holatda butun model INFEASIBLE bo'lib, hech qanday jadval chiqmasdi
        # (bu loyihada avval bir necha marta uchragan xato — schedule-generation.md).
        dept_order = dict(
            Department.objects.filter(organization=organization)
            .values_list('id', 'order')
        )
        dept_day: defaultdict[tuple, list] = defaultdict(list)
        for (ti, si), var in x.items():
            d_id = tasks[ti].department_id
            if d_id is None:
                continue
            if slot_building.get((ti, si)) not in regional_building_ids:
                continue
            dept_day[(d_id, slots[si].date)].append(var)

        dept_pairs: defaultdict[int, list] = defaultdict(list)
        for (d_id, d), vars_ in dept_day.items():
            p = model.new_bool_var(f'dd_{d_id}_{d}')
            for v in vars_:
                model.add_implication(v, p)
            dept_pairs[d_id].append((day_index[d], p))

        dept_bounds: dict[int, tuple] = {}
        for d_id, pairs in dept_pairs.items():
            idxs = [i for i, _ in pairs]
            lo, hi = min(idxs), max(idxs)
            df = model.new_int_var(lo, hi, f'dfirst_{d_id}')
            dl = model.new_int_var(lo, hi, f'dlast_{d_id}')
            for i, p in pairs:
                model.add(df <= i).only_enforce_if(p)
                model.add(dl >= i).only_enforce_if(p)
            dept_bounds[d_id] = (df, dl, lo, hi)
            if hi > lo:
                spread = model.new_int_var(0, hi - lo, f'dspread_{d_id}')
                model.add(spread == dl - df)
                dept_spread_terms.append(spread)

        # Tartib buzilishi: order bo'yicha ketma-ket kafedralar uchun
        ordered_ids = sorted(dept_bounds, key=lambda i: (dept_order.get(i, 999), i))
        for a, b in zip(ordered_ids, ordered_ids[1:]):
            df_a, dl_a, lo_a, hi_a = dept_bounds[a]
            df_b, dl_b, lo_b, hi_b = dept_bounds[b]
            # b oldingi kafedra (a) tugagandan keyin boshlanishi kerak:
            # ideal holda dfirst_b > dlast_a. Buzilish = dlast_a - dfirst_b + 1
            ov = model.new_int_var(0, max(hi_a - lo_b + 1, 0), f'dov_{a}_{b}')
            model.add(ov >= dl_a - df_b + 1)
            dept_order_terms.append(ov)

    # ── KO'CHMA MASHG'ULOT: o'quv jarayonining OXIRIDA, KETMA-KET ─────────────
    # Foydalanuvchi talabi: ko'chma mashg'ulot (`CurriculumSubject.field_hours`)
    # soatlari o'quv jarayonining oxiriga qo'yilsin va ketma-ket bo'lsin —
    # chunki bunda tinglovchilar biror joyga borib amaliyot qiladi (shu sababli
    # ularga xona ham biriktirilmaydi, 9-bo'limga qarang).
    # Bu qoida VILOYATGA BOG'LIQ EMAS — barcha binolarda amal qiladi.
    #
    # Ikkita jazo:
    #   1) `field_early` — dars kuni guruh davrining oxiridan qancha uzoq bo'lsa,
    #      shuncha katta jazo (ya'ni oxirga tortiladi)
    #   2) `field_span`  — birinchi va oxirgi ko'chma dars kuni orasidagi masofa
    #      (ya'ni kunlar yonma-yon bo'lsin, bo'lib-bo'lib emas)
    # (task_index, ifoda) juftliklari — bosqichlarga (viloyat/markaz) ajratish uchun
    field_early_pairs = []
    field_span_pairs = []
    field_fill_pairs = []   # (guruh, bo'sh para soni) — chala kun jazosi
    field_day_index = {d: i for i, d in enumerate(sorted({s_.date for s_ in slots}))}
    field_task_day: defaultdict[tuple, list] = defaultdict(list)
    group_field_day: defaultdict[tuple, list] = defaultdict(list)
    # (var, para.order) — ko'chma kunidagi para-darajasidagi qoidalar uchun
    group_field_para: defaultdict[tuple, list] = defaultdict(list)
    group_other_para: defaultdict[tuple, list] = defaultdict(list)
    for (ti, si), var in x.items():
        key_gd = (tasks[ti].group_id, slots[si].date)
        p_order = para_by_id[slots[si].para_id].order
        if tasks[ti].is_field:
            field_task_day[(ti, slots[si].date)].append(var)
            group_field_day[key_gd].append(var)
            group_field_para[key_gd].append((var, p_order))
        else:
            group_other_para[key_gd].append((var, p_order))

    # ── QAT'IY: guruhning ko'chma DAVRI yaxlit, ichida boshqa fan yo'q ───────
    # **Nega guruh darajasida ham kerak (real ma'lumotda o'lchangan)**: har bir
    # ko'chma FAN alohida ketma-ket bo'lishi YETARLI EMAS. Bazadagi #19 jadvalda
    # "Trener-seleksioner" guruhida 26.09 ko'chma, 28.09 oddiy darslar, 29.09
    # yana ko'chma bo'lib chiqdi — ikkala ko'chma fan ham alohida uzluksiz,
    # lekin guruhning ko'chma DAVRI oddiy kun bilan bo'lingan edi.
    #
    # Ikki qism:
    #   1. `gf[g,d]` — shu kuni guruhda ko'chma dars bormi. Bo'lsa, o'sha kuni
    #      boshqa fanlar FAQAT 1- va 2-parada o'tilishi mumkin (qoida 1.3/2.2).
    #   2. Guruhning ko'chma kunlari KETMA-KET: `oxirgi - birinchi + 1 == soni`.
    # Kunlarni oldindan qat'iy band qilish (`field_days`ni oddiy fanlarga ham
    # taqiqlash) sinab ko'rildi va REDDILDI — zaxira kuni behuda band bo'lib,
    # 1283 dan 16 ta oddiy dars yo'qolgan edi. Dinamik `gf` esa faqat haqiqatan
    # ishlatilgan kunni cheklaydi.
    gf_by_group: defaultdict[int, list] = defaultdict(list)
    for key_gd, f_vars in group_field_day.items():
        gf = model.new_bool_var(f'gfield_{key_gd[0]}_{key_gd[1]}')
        for v in f_vars:
            model.add_implication(v, gf)
        # Teskari bog'lanish SHART — busiz solver ko'chma darsi YO'Q kunlarga
        # ham gf=1 qo'yib, ketma-ketlik cheklovini "teshik to'ldirish" bilan
        # aldab o'tishi va oddiy darslarni behuda bloklashi mumkin edi.
        model.add(gf <= sum(f_vars))

        # ── Ko'chma kunida boshqa fan — FAQAT 1- va 2-parada ─────────────────
        # **Foydalanuvchi qoidasi 1.3 / 2.2**: "agarda bir kunda ko'chma
        # mashg'ulotdan boshqa dars qo'yish mumkin bo'lsa, faqat 1 va 2
        # paralarga qo'yish mumkin". Ya'ni tinglovchilar ertalab auditoriyada
        # o'qib, keyin amaliyotga chiqib ketadi.
        #
        # Bu avvalgi "kunida UMUMAN boshqa fan yo'q" qoidasining o'rniga keldi.
        # Avvalgisi sig'imni ko'p yeb yuborardi (kun to'liq band bo'lardi,
        # ko'chma paralar esa odatda 1–2 ta) — shuning uchun u faqat zaxirasi
        # yetadigan guruhlarda qo'llanardi (`field_exclusive`). Endi 1–2-paralar
        # oddiy fanlarga ochiq qolgani uchun behuda yo'qotish deyarli yo'q va
        # qoida BARCHA guruhlarga bir xil qo'llanadi.
        for w, w_ord in group_other_para.get(key_gd, ()):
            if w_ord > FIELD_DAY_OTHER_MAX_PARA:
                model.add(gf + w <= 1)

        # Ko'chma dars boshlangach — o'sha kuni ortidan oddiy dars qo'yilmaydi
        # (tinglovchilar allaqachon tashqarida). Ya'ni kun ichida tartib har
        # doim: oddiy darslar → ko'chma mashg'ulot.
        for fv, f_ord in group_field_para.get(key_gd, ()):
            for w, w_ord in group_other_para.get(key_gd, ()):
                if w_ord > f_ord:
                    model.add(fv + w <= 1)

        gf_by_group[key_gd[0]].append((field_day_index[key_gd[1]], gf, key_gd[1]))

    # ── QAT'IY: ko'chma blok MINIMAL kunga sig'sin (suyultirilmasin) ─────────
    # `field_min_days` — guruhning ko'chma paralari eng yirik sig'imli kunlarga
    # to'liq joylashtirilganda kerak bo'ladigan kun soni. Bundan oshirmaslik
    # ko'chma kunlarini TO'LA qiladi, ya'ni "1 ko'chma + 2 oddiy" kabi
    # suyultirilgan kunlar hosil bo'lmaydi. Oddiy fanlar uchun 1–2-para
    # baribir ochiq qoladi — lekin faqat blokda haqiqatan bo'sh joy qolganda
    # (masalan 6 para, kunlik sig'im 4 → 2 kun, 2 slot bo'sh).
    for gid, triples in gf_by_group.items():
        limit = field_min_days.get(gid)
        if limit and len(triples) > limit:
            model.add(sum(p for _i, p, _d in triples) <= limit)

    for gid, triples in gf_by_group.items():
        if len(triples) < 2:
            continue
        idxs = [i for i, _, _ in triples]
        lo, hi = min(idxs), max(idxs)
        gfirst = model.new_int_var(lo, hi, f'gffirst_{gid}')
        glast_ = model.new_int_var(lo, hi, f'gflast_{gid}')
        for i, p, _d in triples:
            model.add(gfirst <= i).only_enforce_if(p)
            model.add(glast_ >= i).only_enforce_if(p)
        model.add(glast_ - gfirst + 1 == sum(p for _, p, _d in triples))

        # ── Bo'sh paralar FAQAT blokning OXIRGI kunida ───────────────────────
        # Foydalanuvchi qoidasi: "smena uchun yetarli paralar bo'lmasa, ketma-ket
        # ko'chma mashg'ulot kunlarining OXIRGI kunida bo'sh paralar bo'lishi
        # mumkin". Ya'ni oldingi kunlar to'la bo'lishi shart — chala kun
        # blokning o'rtasida turmasin.
        # **Yumshoq jazo, QAT'IY emas (o'lchangan)**: dastlab qat'iy tenglik
        # (`sum == cap` only_enforce_if) qilingan edi — natijada 1283 dan
        # 1279 ta dars joylashdi, ya'ni 4 ta dars YO'QOLDI. "Hech narsa
        # yo'qolmasin" esa eng ustuvor qoida, shuning uchun bu talab jazo
        # sifatida qo'yiladi: keyingi kunda ko'chma dars bo'lsa, oldingi
        # kundagi bo'sh paralar jarima hisoblanadi.
        ordered = sorted(triples)
        for (_i_a, _p_a, d_a), (_i_b, p_b, _d_b) in zip(ordered, ordered[1:]):
            da_a = day_map.get((gid, d_a))
            if da_a is None:
                continue
            cap_a = _paras_by_shift.get(da_a.shift_id, 0)
            vars_a = group_field_day.get((gid, d_a), [])
            if cap_a and vars_a:
                sh = model.new_int_var(0, cap_a, f'fshort_{gid}_{d_a}')
                model.add(sh >= cap_a * p_b - sum(vars_a))
                field_fill_pairs.append((gid, sh))

    if field_task_day:
        # Har guruh uchun oxirgi dars kuni indeksi — "oxirga yaqinlik" shundan
        group_last_idx: dict[int, int] = {}
        for ti, task in enumerate(tasks):
            if not task.is_field:
                continue
            idxs = [
                field_day_index[slots[si].date]
                for si in range(len(slots)) if (ti, si) in x
            ]
            if idxs:
                group_last_idx[ti] = max(idxs)

        fd_bool: dict[tuple, object] = {}
        for (ti, d), vars_ in field_task_day.items():
            p = model.new_bool_var(f'fday_{ti}_{d}')
            for v in vars_:
                model.add_implication(v, p)
            # **Teskari implikatsiya SHART** — quyidagi ketma-ketlik cheklovi
            # uchun `p` aynan "shu kunda shu fanning darsi bor" degani bo'lishi
            # kerak. Faqat `v -> p` bo'lsa, solver darsi yo'q kunlarga ham p=1
            # qo'yib, "teshiklarni to'ldirib" cheklovni aldab o'tishi mumkin edi.
            model.add(p <= sum(vars_))
            fd_bool[(ti, d)] = p
            # Oxirdan uzoqlik jazosi: har bir dars uchun (oxirgi_kun - shu_kun).
            # Qo'shimcha o'zgaruvchi kerak emas — to'g'ridan-to'g'ri chiziqli
            # ifoda (modelni yengil saqlash uchun).
            dist = group_last_idx.get(ti, 0) - field_day_index[d]
            if dist > 0:
                field_early_pairs.append((ti, dist * sum(vars_)))

        by_task: defaultdict[int, list] = defaultdict(list)
        for (ti, d), p in fd_bool.items():
            by_task[ti].append((field_day_index[d], p))

        # (ti) -> (birinchi_kun_var, oxirgi_kun_var) — quyida ko'chma fanlarni
        # bir-biridan ajratishda (qoida 1.2) ham ishlatiladi
        field_bounds: dict[int, tuple] = {}
        for ti, pairs in by_task.items():
            if len(pairs) < 2:
                continue
            idxs = [i for i, _ in pairs]
            lo, hi = min(idxs), max(idxs)
            f_ = model.new_int_var(lo, hi, f'ffirst_{ti}')
            l_ = model.new_int_var(lo, hi, f'flast_{ti}')
            for i, p in pairs:
                model.add(f_ <= i).only_enforce_if(p)
                model.add(l_ >= i).only_enforce_if(p)
            sp = model.new_int_var(0, hi - lo, f'fspan_{ti}')
            model.add(sp == l_ - f_)
            field_span_pairs.append((ti, sp))
            field_bounds[ti] = (f_, l_, lo, hi)

            # ── QAT'IY: ko'chma mashg'ulot kunlari KETMA-KET bo'lishi SHART ──
            # Foydalanuvchi talabi: "har bir guruhda bu fan ketma-ket o'tilishi
            # shart". Yumshoq jazo (`field_span_terms`) yetarli bo'lmadi —
            # 20 fandan atigi 4 tasi ketma-ket chiqardi.
            # `oxirgi - birinchi + 1 == ishlatilgan kunlar soni` — bu aynan
            # "orada bo'sh kun yo'q" degani.
            # Bu cheklov modelni bloklab qo'ymaydi: Constraint 1 `<=` bo'lgani
            # uchun eng yomon holatda kamroq dars joylashadi, lekin amalda
            # (o'lchangan) barcha 1283 para joylashishda davom etadi — chunki
            # ko'chma fanning paralari kam (odatda 3 para = 1–2 kun) va
            # guruhning oxirgi kunlarida yetarli joy bor.
            model.add(l_ - f_ + 1 == sum(p for _, p in pairs))

        # ── QAT'IY: bir guruhdagi TURLI ko'chma fanlar ARALASHMAYDI ──────────
        # **Foydalanuvchi qoidasi 1.2 / 2.2**: "ko'chma mashg'ulotlarni 2 fan va
        # 2 ta o'qituvchi o'tsa, bu fanlar/o'qituvchilar tartib bilan o'tishi
        # kerak — bir o'qituvchi darslarining orasiga boshqa o'qituvchining
        # darslari qo'shilib qolmasligi kerak."
        #
        # Har bir fan alohida ketma-ket bo'lishi (yuqoridagi cheklov) YETARLI
        # EMAS: A fani 1–2-kunlarda, B fani 2–3-kunlarda bo'lsa, ikkalasi ham
        # "ketma-ket", lekin 2-kunda ARALASHIB ketadi. Shuning uchun bloklar
        # to'liq ajratiladi: yo A butunlay B dan oldin, yo aksincha.
        # Tartibni solverning o'zi tanlaydi (`seq` bool) — qaysi fan oldin
        # kelishi jadval sig'imiga qarab qulayroq bo'lishi mumkin.
        field_by_group: defaultdict[int, list] = defaultdict(list)
        for ti in field_bounds:
            field_by_group[tasks[ti].group_id].append(ti)

        for gid, tis in field_by_group.items():
            if len(tis) < 2:
                continue
            tis.sort()
            for ai in range(len(tis)):
                for bi in range(ai + 1, len(tis)):
                    a, b = tis[ai], tis[bi]
                    fa, la, lo_a, hi_a = field_bounds[a]
                    fb, lb, lo_b, hi_b = field_bounds[b]
                    # Ikkala yo'nalish ham imkonsiz bo'lsa (oyna 1 kunlik) —
                    # cheklov qo'yilmaydi, aks holda butun model INFEASIBLE
                    # bo'lib qolardi (bu loyihada avval uchragan xato turi).
                    if hi_b <= lo_a and hi_a <= lo_b:
                        continue
                    seq = model.new_bool_var(f'fseq_{a}_{b}')
                    model.add(fb >= la + 1).only_enforce_if(seq)
                    model.add(fa >= lb + 1).only_enforce_if(~seq)

    # ── 8. YECHISH — IKKI BOSQICHLI (leksikografik) ───────────────────────────
    # **Nega ikki bosqich (haqiqiy muammo, o'lchangan)**: dastlab bitta qo'shma
    # maqsad ishlatilgan edi — `1000*joylashgan - jazolar`. Nazariy jihatdan
    # koeffitsiyent yetarlicha katta (darsni qurbon qilish 1000 ga tushadi,
    # tejash esa ko'pi bilan ~30), lekin AMALDA solver 90 soniyada shu
    # optimumni TOPA olmadi va 1161 o'rniga 1159 para joylashtirdi — ya'ni
    # ixchamlik talablari qo'shilgani darslarning yo'qolishiga olib keldi.
    #
    # Yechim: avval FAQAT darslar sonini maksimallashtiramiz (bu masala yengil,
    # tez OPTIMAL bo'ladi), so'ng topilgan sonni QAT'IY quyi chegara sifatida
    # qo'yib (`sum(x) >= best`), ikkinchi bosqichda faqat ixchamlikni
    # optimallashtiramiz. Shunda darslar soni hech qachon kamaymaydi, ixchamlik
    # esa qolgan vaqt imkon bergancha yaxshilanadi.
    total_placed_expr = sum(x.values())

    # ── 8a. 1-BOSQICH: maksimal dars soni ─────────────────────────────────────
    # **Erta to'xtash (o'lchangan)**: bu bosqichning nazariy maksimumi ma'lum —
    # barcha vazifalarning `paras_needed` yig'indisi. Solver odatda shu qiymatni
    # 15–50 soniyada topadi, lekin qolgan butun vaqtni uning OPTIMAL ekanini
    # ISBOTLASHGA sarflaydi (natija o'zgarmaydi). O'lchangan holat: 84 soniyalik
    # byudjetning ~30–60 soniyasi shunga ketardi, VILOYAT bosqichiga esa vaqt
    # yetmay natija har safar sezilarli tebranardi (obj 30815 ↔ 36255).
    # Maksimumga yetgan zahoti to'xtatib, qolgan vaqtni keyingi bosqichlarga
    # beramiz.
    class _StopAtMax(cp_model.CpSolverSolutionCallback):
        def __init__(self, target):
            super().__init__()
            self._target = target

        def on_solution_callback(self):
            if self.objective_value >= self._target:
                self.stop_search()

    # Ulush 0.5 — erta to'xtash tufayli maksimumga yetilsa vaqt baribir
    # keyingi bosqichlarga o'tadi, yetilmasa esa qo'shimcha vaqt to'g'ridan-
    # to'g'ri ko'proq dars degani (o'lchangan: 0.35 da bir marta 84 soniya
    # yetmay 1281/1283 bo'lib qolgan edi — bu esa eng ustuvor qoidaning
    # buzilishi).
    _p(22, "Darslar jadvalga joylashtirilmoqda",
       f"Jami {sum(t.paras_needed for t in tasks)} ta dars joylashtirilishi kerak. "
       "Bu eng muhim qadam — hech bir dars tushib qolmasligi shart.")

    # ── QAYTA URINISH: 1-bosqich maksimumga yetmasa ──────────────────────────
    # O'lchangan HAQIQIY muammo: bir xil ma'lumot va bir xil kodda 5 ta ketma-ket
    # ishga tushirish 1283, 1282, 1283, 1273, 1275 berdi — ya'ni ~40% hollarda
    # ENG USTUVOR qoida ("hech bir dars yo'qolmasin") buzilardi. Sabab kodda
    # emas: CP-SAT ko'p oqimli (`num_search_workers`), qidiruv yo'li har safar
    # boshqacha va ba'zan 120 soniyalik byudjet ichida maksimumga yetmaydi.
    #
    # Yechim: maksimumga yetilmasa, boshqa `random_seed` bilan qayta urinish —
    # eng yaxshi yechim `add_hint` orqali boshlang'ich nuqta sifatida beriladi,
    # ya'ni natija faqat yaxshilanadi. Byudjet 0.5 dan 0.75 gacha kengaytiriladi
    # (faqat KERAK BO'LGANDA — maksimumga yetilsa qo'shimcha urinish umuman
    # bo'lmaydi va vaqt avvalgidek keyingi bosqichlarga o'tadi).
    _p1_target = sum(t.paras_needed for t in tasks)
    _p1_first = max(5.0, time_limit_seconds * 0.5)
    _p1_cap = max(_p1_first, time_limit_seconds * 0.75)
    model.maximize(total_placed_expr)

    phase1_time = 0.0
    best_obj = -1
    phase1_solution: dict[tuple, int] = {}
    status_code = cp_model.UNKNOWN
    for _attempt in range(3):
        if _attempt == 0:
            _budget = _p1_first
        else:
            _budget = _p1_cap - phase1_time
            if _budget < 10.0:
                break
            model.clear_hints()
            for _k, _v in x.items():
                model.add_hint(_v, phase1_solution[_k])
        solver.parameters.random_seed = _attempt * 7919
        solver.parameters.max_time_in_seconds = max(5.0, _budget)
        status_code = solver.solve(model, _StopAtMax(_p1_target))
        phase1_time += solver.wall_time
        if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            _obj = int(solver.objective_value)
            if _obj > best_obj:
                best_obj = _obj
                phase1_solution = {k: solver.value(v) for k, v in x.items()}
        if best_obj >= _p1_target or not phase1_solution:
            break
    solver.parameters.random_seed = 0
    model.clear_hints()

    _phase1_note = (f'1-MAKSIMAL: {solver.status_name(status_code)} '
                    f'{phase1_time:.0f}s joylashgan='
                    f'{best_obj if best_obj >= 0 else "—"}'
                    + (f' ({_attempt + 1} urinish)' if _attempt else ''))

    # ── 8b/8c. BOSQICHLAR TARTIBI: AVVAL VILOYAT, KEYIN MARKAZ ───────────────
    # **Foydalanuvchi talabi (muhim tartib!)**: "Birinchi bo'lib viloyatlar uchun
    # jadvalni shakllantirib, keyin boshqa lokatsiyalarda o'qituvchilarning
    # bo'sh vaqtiga qarab jadvalni shakllantirish kerak."
    # Ya'ni viloyat (komandirovka) BIRINCHI navbatda optimallashtiriladi, markaz
    # esa undan qolgan bo'shliqqa moslashadi — teskarisi emas.
    #
    # 2-BOSQICH — VILOYAT (chekinib bo'lmaydigan qoidalar), vaznlar:
    #   100  kafedra tartibi buzilishi (Department.order) — avval bitta kafedra
    #        o'z fanlarini o'tib tugatsin, keyin keyingisi chiqsin
    #   50   kafedra bloki tarqoqligi — kafedra ixcham blokda ishlasin
    #   40   o'qituvchining viloyatdagi BO'SH kuni — borgan o'qituvchi bo'sh
    #        kun qoldirmasdan darslarini ketma-ket o'tib qaytsin
    #   60   safar (o'qituvchi × hafta) — bir marta borsin
    #   25   o'qituvchi-kun — kam kun tursin
    #   20   vazifa-kun va vazifa span — fan kam va yonma-yon kunlarda tugasin
    # Viloyatda haftalik reja chetlanishi JAZOLANMAYDI (foydalanuvchi bilan
    # aniqlashtirilgan: komandirovka ixchamligi haftalik rejadan muhimroq).
    # **Foydalanuvchi belgilagan BOSQICHLAR TARTIBI**:
    #   1. viloyatdagi KO'CHMA darslar
    #   2. boshqa binolardagi KO'CHMA darslar
    #   3. viloyatdagi qolgan darslar
    #   4. boshqa binolardagi qolgan darslar
    # Har bosqich oldingisining natijasini QOTIRIB oladi, ya'ni oldingi
    # bosqichda hal qilingan narsa keyingisida buzilmaydi. Bu — ustuvorlik
    # tartibi: ko'chma mashg'ulot eng qulay joyni birinchi bo'lib egallaydi,
    # qolgan darslar undan qolgan bo'shliqqa moslashadi.
    field_tasks = {ti for ti, t in enumerate(tasks) if t.is_field}
    field_regional = field_tasks & regional_tasks
    field_central = field_tasks - regional_tasks

    def _terms_for(term_pairs, weight, wanted):
        """(task_index, var) juftliklaridan faqat kerakli vazifalarnikini oladi."""
        sel = [v for ti, v in term_pairs if ti in wanted]
        return [weight * sum(sel)] if sel else []

    # 1/2-BOSQICH: ko'chma mashg'ulot (avval viloyat, keyin markaz).
    #   60  oxirdan uzoqlik — o'quv jarayonining oxiriga tortiladi
    #   15  span — kunlar yonma-yon (qat'iy cheklov ustiga qo'shimcha silliqlash)
    reg_field_groups = {tasks[ti].group_id for ti in field_regional}
    cen_field_groups = {tasks[ti].group_id for ti in field_central}
    # **Viloyatda `field_early` vazni PAST (5)** — foydalanuvchi qoidasi:
    # "ko'chmani oxiriga mixlangan bo'lsa, unda boshroqqa tortish kerak,
    # bunga mumkin". Ya'ni viloyatda "davr oxirida bo'lsin" faqat teng
    # imkoniyatlarda ishlaydigan afzallik; asosiysi — o'qituvchida bo'sh
    # kun qolmasligi. Markazda esa vazn avvalgidek yuqori (60).
    phase_field_reg = (_terms_for(field_early_pairs, 5, field_regional)
                       + _terms_for(field_span_pairs, 15, field_regional)
                       + _terms_for(field_fill_pairs, 25, reg_field_groups))
    phase_field_cen = (_terms_for(field_early_pairs, 60, field_central)
                       + _terms_for(field_span_pairs, 15, field_central)
                       + _terms_for(field_fill_pairs, 25, cen_field_groups))

    # 3-BOSQICH: viloyatdagi qolgan (ko'chma bo'lmagan) darslar.
    # Viloyatda haftalik reja chetlanishi JAZOLANMAYDI (foydalanuvchi bilan
    # aniqlashtirilgan: komandirovka ixchamligi haftalik rejadan muhimroq).
    # **Vaznlar qayta balanslandi (o'lchangan)**: kafedra navbati endi
    # STRUKTURAVIY kafolatlangan (`dept_window` — x o'zgaruvchilari oynadan
    # tashqariga umuman yaratilmaydi), shuning uchun `dept_order`/`dept_spread`
    # jazolari deyarli ortiqcha bo'lib qoldi — ular baribir 0 ga yaqin turadi,
    # lekin katta vazn bilan solverning e'tiborini o'ziga tortib, ASOSIY
    # maqsadni (o'qituvchi komandirovkasining ixchamligi) siqib qo'yardi.
    # Foydalanuvchi talabi: "o'qituvchi darslarini iloji boricha tezroq o'qitib
    # qaytishi shart" — shuning uchun eng katta vazn `teacher_gap` (safar
    # ichidagi BO'SH kunlar) ga beriladi.
    phase_regional = []
    # **Eng katta vazn — O'QITUVCHI-KUN** (foydalanuvchi talabi: "o'qituvchi
    # iloji boricha kamroq kun qolishi, bir necha kunda hamma guruh uchun
    # darslarini o'tib kelishi kerak"). Avval eng katta vazn `teacher_gap`
    # (bo'shliq) da edi — lekin bo'shliqni kamaytirish kun sonini kamaytirmaydi,
    # aksincha kunlarni yonma-yon qilib qo'yib, sonini o'sha holicha qoldiradi.
    # Kun soni kamaysa, bo'shliq ham tabiiy ravishda qisqaradi.
    if presence_vars:
        phase_regional.append(REGIONAL_PRESENCE_WEIGHT * sum(presence_vars))
    # "Bo'sh kun qolishi mumkin emas" (qoida 3) — indikator literal, JUDA katta
    # vazn: amalda qat'iy cheklov kabi ishlaydi, lekin modelni bloklamaydi.
    if teacher_gap_hard_terms:
        phase_regional.append(5000 * sum(teacher_gap_hard_terms))
    if teacher_gap_terms:
        phase_regional.append(100 * sum(teacher_gap_terms))
    # "O'qituvchilar limitini yengilroq qilish kerak" (qoida 1.6) — safarlar
    # sonining vazni pasaytirildi: asosiy maqsad KUN soni (`presence`) va
    # bo'shliqsizlik, "bir vaqtda nechta o'qituvchi" emas.
    if trip_vars:
        phase_regional.append(50 * sum(trip_vars))
    if task_day_vars:
        phase_regional.append(20 * sum(task_day_vars))
    if span_terms:
        phase_regional.append(20 * sum(span_terms))
    # Strukturaviy kafolatga qo'shimcha (kichik vazn — faqat teng imkoniyatlarda
    # tartibni saqlash uchun)
    if dept_order_terms:
        phase_regional.append(10 * sum(dept_order_terms))
    if dept_spread_terms:
        phase_regional.append(5 * sum(dept_spread_terms))
    # PARCHALANISH (viloyat) — (o'qituvchi, guruh, kun) uchliklari kam bo'lsin,
    # ya'ni o'qituvchi kelganda 1 emas, 2 paradan o'tsin. Qo'lda tuzilgan may
    # jadvalida 2 paralik blok 38%, 1 paralik 53%; dasturda esa 24% / 64% edi.
    # Vazn `presence` (150) dan past — kun sonini kamaytirish baribir ustun,
    # lekin `trip`/`task_day` bilan bir darajada, chunki blokni yiriklashtirish
    # kun sonini ham tabiiy ravishda kamaytiradi (bir xil yo'nalishdagi maqsad).
    reg_tg_bools = [b for k, b in tg_day_bools.items()
                    if tg_day_tasks[k] & regional_tasks]
    if reg_tg_bools:
        phase_regional.append(40 * sum(reg_tg_bools))

    # 4-BOSQICH: boshqa binolardagi qolgan darslar.
    #   30  markazdagi haftalik rejadan chetlanish (akademik talab)
    #    1  ishlatilgan (guruh, kun) — kunlar to'la bo'lsin
    central_dev = [d for ti, d in week_dev_vars if ti not in regional_tasks]
    phase_central = []
    if central_dev:
        phase_central.append(30 * sum(central_dev))
    if group_day_used:
        phase_central.append(sum(group_day_used.values()))
    # Parchalanish: (o'qituvchi, guruh, kun) uchliklari kam bo'lsin — ya'ni
    # o'qituvchi kelganda 1 emas, 2 paradan o'tsin. Vazn `group_day_used`
    # (kunlar to'la bo'lsin, vazn 1) dan biroz yuqori, lekin haftalik reja
    # chetlanishidan (30) ancha past — akademik talab baribir ustun turadi.
    # Vazn 12 (40 emas!) — markazda HAFTALIK REJA ustun turishi kerak
    # (foydalanuvchi qoidasi: "haftalik cheklov markazda saqlanib qolishi
    # kerak"). `central_dev` vazni 30, shuning uchun parchalanish jazosi
    # undan PAST bo'lishi shart — aks holda solver haftalik rejani buzib
    # bloklarni yiriklashtirishni afzal ko'rardi.
    cen_tg_bools = [b for k, b in tg_day_bools.items()
                    if not (tg_day_tasks[k] & regional_tasks)]
    if cen_tg_bools:
        phase_central.append(12 * sum(cen_tg_bools))

    # Har bosqich yechimi saqlab qo'yiladi — keyingi bosqich vaqt yetmay
    # yechimsiz qaytsa ham jadval yo'qolib ketmasligi uchun (`solver` obyektida
    # faqat OXIRGI solve natijasi turadi, muvaffaqiyatsiz bo'lsa o'qib bo'lmaydi).
    # (1-bosqichda bir necha urinish bo'lishi mumkin — `solver` obyektida faqat
    # OXIRGISI turadi, shuning uchun ENG YAXSHI yechim alohida saqlangan.)
    solution: dict[tuple, int] = dict(phase1_solution)

    phase_log: list[str] = [_phase1_note]

    # Bosqichning texnik nomi -> (foiz, foydalanuvchiga ko'rinadigan nom, izoh)
    _PHASE_UI = {
        "KO'CHMA-VILOYAT": (48, "Viloyatdagi ko'chma mashg'ulotlar tartibga solinmoqda",
                            "Ko'chma mashg'ulotlar o'quv davrining oxiriga, ketma-ket "
                            "kunlarga yig'ilmoqda."),
        "VILOYAT-BO'SHLIQ-1": (56, "O'qituvchilarning bo'sh kunlari yopilmoqda",
                               "Viloyatga borgan o'qituvchi bo'sh kun qoldirmasdan "
                               "darslarini o'tib qaytishi kerak."),
        "VILOYAT-BO'SHLIQ-2": (63, "O'qituvchilarning bo'sh kunlari yopilmoqda",
                               "Ikkinchi urinish — yanada yaxshiroq variant izlanmoqda."),
        "VILOYAT-BO'SHLIQ-3": (70, "O'qituvchilarning bo'sh kunlari yopilmoqda",
                               "Uchinchi urinish — yanada yaxshiroq variant izlanmoqda."),
        'VILOYAT-SAFAR': (78, "Komandirovka kunlari qisqartirilmoqda",
                          "Har bir o'qituvchi viloyatda iloji boricha kam kun "
                          "turishi uchun darslar zichlashtirilmoqda."),
        'VILOYAT': (85, "Viloyat jadvali yakunlanmoqda",
                    "Kafedra navbati va qolgan viloyat qoidalari tekshirilmoqda."),
        "KO'CHMA-MARKAZ": (90, "Markazdagi ko'chma mashg'ulotlar",
                           "Markaziy binolardagi ko'chma mashg'ulotlar davr oxiriga "
                           "joylashtirilmoqda."),
        'MARKAZ': (94, "Markaz jadvali yakunlanmoqda",
                   "Haftalik reja bo'yicha darslar o'z haftalariga tortilmoqda va "
                   "kunlar to'ldirilmoqda."),
    }

    def _run_phase(name, objective_terms, seconds, bound_after=False):
        """Joriy yechimni saqlab, berilgan maqsadni minimallashtiradi.
        Sarflangan vaqtni qaytaradi (bosqich erta tugasa, qolgani keyingisiga).

        `bound_after=True` — bosqich erishgan qiymat QAT'IY yuqori chegara
        qilib qo'yiladi. Bu `_freeze()`ga muqobil, YUMSHOQROQ usul: natija
        sifati saqlanadi, lekin vazifalar keyingi bosqichlarda hamon
        ko'chirilishi mumkin. Ko'chma mashg'ulot uchun aynan shu kerak —
        blok davr oxirida qolishi shart, lekin uni o'qituvchining boshqa
        darslariga YONMA-YON surish imkoni yopilmasligi kerak (aks holda
        o'qituvchida bo'sh kun paydo bo'ladi).
        """
        nonlocal solution, status_code
        ui = _PHASE_UI.get(name)
        if ui:
            _p(ui[0], ui[1], ui[2])
        if not objective_terms or not solution:
            phase_log.append(f'{name}: o\'tkazib yuborildi')
            return 0.0
        model.minimize(sum(objective_terms))
        model.clear_hints()
        for k_, v_ in x.items():
            model.add_hint(v_, solution[k_])
        solver.parameters.max_time_in_seconds = max(5.0, seconds)
        st = solver.solve(model)
        ok = st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        if ok:
            status_code = st
            solution = {k_: solver.value(v_) for k_, v_ in x.items()}
            if bound_after:
                model.add(sum(objective_terms) <= round(solver.objective_value))
        # Diagnostika: bosqich haqiqatan ishladimi va maqsad qiymati qanday —
        # aks holda "qoida qo'shdim, lekin natijaga ta'sir qilmadi" holatini
        # aniqlash imkonsiz bo'lib qoladi (real tajriba: kafedra navbati
        # qo'shilgan-u, bosqich INFEASIBLE qaytarib jimgina o'tkazib yuborilgan edi)
        phase_log.append(
            f'{name}: {solver.status_name(st)} '
            f'{solver.wall_time:.0f}s '
            f'obj={solver.objective_value if ok else "—"}'
        )
        return solver.wall_time

    if solution:
        best_placed = sum(solution.values())
        model.add(total_placed_expr >= best_placed)

    remaining = max(5.0, time_limit_seconds - phase1_time)

    # ── MARKAZ UCHUN BUDJETNI OLDINDAN AJRATISH ──────────────────────────────
    # **Haqiqiy muammo (o'lchangan)**: viloyat bosqichlari `remaining` ni
    # ketma-ket foizlab bo'lib olardi (`* 0.5`, `* 0.55`, ...) va oxirgi MARKAZ
    # bosqichiga faqat 5 soniyalik quyi chegara qolardi ("MARKAZ: FEASIBLE 11s"
    # 300 soniyalik limitda). Holbuki 19 guruhdan 13 tasi aynan MARKAZda va
    # parchalanishga qarshi jazo ham o'sha bosqichda — ya'ni eng ko'p guruhga
    # ta'sir qiladigan maqsad amalda umuman optimallashtirilmasdi.
    #
    # Endi markaz ulushi OLDINDAN chetga olinadi va viloyat bosqichlari faqat
    # o'z ulushini bo'ladi. Viloyat ustuvorligi saqlanadi (u baribir birinchi
    # ishlaydi va natijasi `_freeze` bilan qotiriladi), lekin markazni butunlay
    # ochlikda qoldirmaydi.
    central_budget = max(5.0, remaining * 0.35)
    remaining = max(5.0, remaining - central_budget)

    # ── 8b–8e. TO'RT BOSQICH (foydalanuvchi belgilagan ustuvorlik tartibi) ───
    # **Nega bosqichma-bosqich va QOTIRISH bilan (o'lchangan)**: barcha
    # maqsadlarni bitta bosqichda birga optimallashtirganda solver 240 soniyada
    # ham yaqinlasha olmadi — natijalar shovqin darajasida o'zgarardi (vaznlarni
    # oshirish ham yordam bermadi), chunki model juda katta (~300 vazifa ×
    # ~700 slot). Har bosqichdan keyin hal qilingan qismni `var == qiymat` bilan
    # qotirib, qidiruv maydonini keskin qisqartiramiz.
    frozen: set = set()

    def _freeze(task_ids):
        """Berilgan vazifalarning joriy yechimini qotiradi (keyingi bosqichlarda
        o'zgarmaydi) — ustuvorligi yuqori bosqich natijasi buzilmasligi uchun."""
        new_ids = task_ids - frozen
        if not new_ids or not solution:
            return
        for (ti, si), var in x.items():
            if ti in new_ids:
                model.add(var == solution[(ti, si)])
        frozen.update(new_ids)

    # **Foydalanuvchi qoidasi 1 va 2 — TARTIB**: "Birinchi bo'lib TO'LIQ viloyat
    # uchun jadval hosil qilinsin... Viloyatlardagi fanlar joylashtirilgandan
    # KEYIN boshqa binolarga o'tish kerak." Shuning uchun viloyatning ikkala
    # bosqichi (ko'chma + qolgan darslar) markazdan OLDIN tugallanadi va
    # qotiriladi — markaz undan qolgan bo'shliqqa moslashadi.
    #
    # **Vaqt taqsimoti (o'lchangan)**: ko'chma bosqichlari kichik masala —
    # ular qat'iy oyna (`field_days`) bilan allaqachon qattiq cheklangan,
    # shuning uchun ko'p vaqt kerak emas va tez OPTIMAL bo'ladi. Avval ularga
    # 20%+25% berilgan edi va VILOYAT bosqichiga juda oz vaqt qolib, natijada
    # o'qituvchi ixchamligi buzildi (real o'lchov: 24 o'qituvchidan atigi 8 tasi
    # bo'sh kunsiz edi, biri 4 kunlik darsni 11 kunga yoyib yuborgan).
    # Endi ko'chma bosqichlariga oz ulush, asosiy vaqt VILOYATga beriladi;
    # bosqich erta tugasa qolgani baribir keyingisiga o'tadi.

    # 1-bosqich: VILOYATdagi ko'chma darslar.
    # **Muhim (o'lchangan)**: bu bosqichdan keyin ko'chma vazifalar QOTIRILMAYDI
    # (`_freeze`), faqat erishilgan sifat yuqori chegara qilib qo'yiladi
    # (`bound_after`). Sabab: qotirilganda o'qituvchining ko'chma bloki bir joyda
    # mixlanib qolib, uning oddiy darslarini o'sha blokka YONMA-YON qo'yib
    # bo'lmasdi — natijada "Pedagogik amaliyot"i bor o'qituvchilarda
    # (masalan #27, #37) viloyatga ikki marta borish, ya'ni BO'SH KUN paydo
    # bo'lardi. Chegara esa blokni davr oxirida va ketma-ket saqlaydi, lekin
    # uni bir necha kun surish imkonini ochiq qoldiradi.
    t = _run_phase("KO'CHMA-VILOYAT", phase_field_reg, remaining * 0.15,
                   bound_after=True)
    remaining = max(5.0, remaining - t)

    # 2-bosqich: viloyatdagi qolgan darslar (eng ko'p vaqt shu yerga).
    # ── VILOYATGA ALOQASI YO'Q VAZIFALARNI QOTIRISH ─────────────────────────
    # **Hal qiluvchi optimizatsiya (o'lchangan)**: bu bosqich maqsadi faqat
    # viloyatga tegishli, lekin model butun tashkilotni (~300 vazifa × ~700
    # slot) o'z ichiga oladi — solver vaqtining katta qismini natijaga umuman
    # ta'sir qilmaydigan markaz vazifalarini surishga sarflaydi va bosqich
    # OPTIMALga yetmaydi. Aloqasiz qismni qotirib, qidiruvni viloyatga
    # yo'naltiramiz.
    # "Aloqador" = viloyat vazifalari **va** viloyatga boradigan
    # o'qituvchilarning markazdagi darslari — chunki (Constraint 2b bo'yicha)
    # o'qituvchining markazdagi darsi butun bir kunni bloklaydi, ya'ni ular
    # ko'chirilmasa viloyat ixchamligini ta'minlab bo'lmaydi.
    regional_teachers = {
        tasks[ti].teacher_id for ti in regional_tasks
        if tasks[ti].teacher_id is not None
    }
    reg_related = set(regional_tasks) | {
        ti for ti, t_ in enumerate(tasks)
        if t_.teacher_id is not None and t_.teacher_id in regional_teachers
    }
    if regional_building_ids:
        _freeze(set(range(len(tasks))) - reg_related)

    # ── VILOYAT IKKI QADAMDA (leksikografik) ────────────────────────────────
    # **Nega (o'lchangan)**: barcha viloyat maqsadlarini (kun soni, bo'sh kun,
    # safar, fan-kun, span, kafedra) bitta og'ir maqsadga qo'shganda solver
    # 120–140 soniyada ham yaqinlasha olmasdi va natija har ishga tushirishda
    # sezilarli tebranardi (o'qituvchi-kun 131 ↔ 150, obj 31785 ↔ 37295).
    # Foydalanuvchi ustuvorligi esa aniq: AVVAL "maksimal kam kun", keyin
    # "bo'sh kun maksimal 1". Shuning uchun avval faqat kun sonini
    # minimallashtiramiz, erishilgan qiymatni QAT'IY chegara qilib qo'yamiz,
    # so'ng qolgan maqsadlarni optimallashtiramiz. Har ikkala qism alohida
    # ancha yengil masala.
    #
    # **O'lchov nima bo'lishi kerak (o'lchangan, muhim)**: dastlab bu qadamda
    # faqat KUN soni (`presence`) minimallashtirilgan edi — natijada
    # o'qituvchi-kun 131→98 ga tushdi (nazariy minimum ~95), LEKIN kunlar
    # tarqoq bo'lib qoldi: masalan 12 darsli o'qituvchi 3 kun ishlab, orasida
    # 8 kun bo'sh turardi. Komandirovka uchun haqiqiy xarajat esa "necha kun
    # ishladi" emas, "necha kun VILOYATDA turdi" — ya'ni birinchi va oxirgi
    # kun orasidagi butun oraliq. Shuning uchun o'lchov `span = kun + bo'shliq`
    # (aynan foydalanuvchi talab qilgan ikkala narsani bitta sonda birlashtiradi).
    if regional_building_ids and presence_vars:
        # ── 1-QADAM: BO'SH KUN (eng ustuvor talab) ───────────────────────────
        # **Foydalanuvchi qoidasi 3 (qat'iy)**: "borgan o'qituvchi umuman bo'sh
        # qolishi mumkin emas". Shuning uchun bu — birinchi va eng ustuvor
        # viloyat qadami; kun sonini kamaytirish undan KEYIN keladi.
        # Maqsad faqat indikator bool'lardan iborat (yengil masala), erishilgan
        # qiymat esa keyingi qadamlar uchun qat'iy chegara bo'lib qoladi —
        # ya'ni kun sonini optimallashtirish bo'shliqni qaytadan ochib
        # yubormaydi.
        # Maqsadga oldindan hisoblangan OYNADAN chetga chiqish ham qo'shiladi:
        # oyna aynan "bo'sh kunsiz va limitga mos" bo'lishi uchun tuzilgan,
        # shuning uchun unga yaqinlashish bo'shliqni yopishning eng to'g'ridan-
        # to'g'ri yo'li. Solver uchun bu MAYDA qadamlar ketma-ketligi (har bir
        # darsni alohida surish), ya'ni u buni topa oladi — bo'shliq
        # indikatorlarining o'zi esa "hammasi yoki hech nima" xarakteriga ega
        # va issiq startdan yaxshilanishi qiyin edi.
        gap_terms_ = []
        if teacher_gap_hard_terms:
            # **Vazn 100 → 1000 (o'lchangan)**: greedy tuzatilgandan keyin
            # struktura 24/24 ga imkon beradi (bir ishga tushirishda erishildi),
            # lekin CP-SAT uni har safar topa olmasdi — oyna chetlanishi
            # (`window_violations`) bilan bo'sh kun deyarli teng vaznda edi.
            # Bo'sh kun ancha muhimroq, shuning uchun farq keskinlashtirildi.
            gap_terms_.append(1000 * sum(teacher_gap_hard_terms))
        if window_violations:
            gap_terms_.append(3 * sum(window_violations))
        if gap_terms_:
            # **QAYTA URINISH (o'lchangan)**: bu bosqich natijasi kuchli
            # tebranardi — bir ishga tushirishda 24/24 (obj=20), boshqasida
            # 20/24 (obj≈1350). Vaqtni oshirish (0.4 → 0.5) YORDAM BERMADI:
            # muammo vaqtda emas, issiq startdan qaysi platoga tushib
            # qolishda. Shuning uchun bosqich uch marta, boshqa-boshqa
            # tasodifiy urug' bilan qayta ishga tushiriladi — har urinish
            # oldingisining yechimidan (`add_hint`) va uning `bound_after`
            # chegarasidan boshlanadi, ya'ni natija faqat yaxshilanadi.
            for attempt in range(3):
                solver.parameters.random_seed = attempt * 7919
                t = _run_phase(f"VILOYAT-BO'SHLIQ-{attempt + 1}", gap_terms_,
                               remaining * 0.22, bound_after=True)
                remaining = max(5.0, remaining - t)
            solver.parameters.random_seed = 0

        # ── 2-QADAM: viloyatda turish davri (kun + bo'shliq) ─────────────────
        span_expr = sum(presence_vars) + (
            sum(teacher_gap_terms) if teacher_gap_terms else 0
        )
        t = _run_phase("VILOYAT-SAFAR", [span_expr], remaining * 0.5)
        remaining = max(5.0, remaining - t)
        # Erishilgan qiymatni Python tomonida qayta hisoblaymiz (yechimdan) va
        # keyingi qadam uchun qat'iy chegara qilib qo'yamiz.
        reg_days_by_teacher: defaultdict[int, set] = defaultdict(set)
        for (ti, si), v_ in solution.items():
            if v_ != 1 or tasks[ti].teacher_id is None:
                continue
            if slot_building.get((ti, si)) in regional_building_ids:
                reg_days_by_teacher[tasks[ti].teacher_id].add(slots[si].date)
        # **Indeks modeldagi bilan BIR XIL bo'lishi shart** — `teacher_gap_terms`
        # ichidagi bo'shliq barcha slot sanalari bo'yicha indeksdan hisoblanadi
        # (faqat viloyat kunlari bo'yicha emas). Boshqa indeks ishlatilsa
        # chegara noto'g'ri chiqib, keyingi qadam INFEASIBLE bo'lib qolardi.
        r_idx = {d: i for i, d in enumerate(sorted({s_.date for s_ in slots}))}
        reg_span_now = sum(
            max(r_idx[d] for d in ds) - min(r_idx[d] for d in ds) + 1
            for ds in reg_days_by_teacher.values()
        )
        if reg_span_now:
            model.add(span_expr <= reg_span_now)

    # VILOYAT bosqichi ilgari `remaining * 0.8` olardi — natijada oxirgi
    # MARKAZ bosqichiga faqat 5 soniyalik quyi chegara qolar edi (o'lchangan:
    # "MARKAZ: FEASIBLE 5s"). MARKAZda esa 13 guruh (viloyatda atigi 5) va
    # aynan parchalanishga qarshi jazo turadi — ya'ni eng ko'p guruhga
    # ta'sir qiladigan maqsad amalda umuman optimallashtirilmasdi.
    t = _run_phase('VILOYAT', phase_regional, remaining * 0.8)
    remaining = max(5.0, remaining - t)
    _freeze(regional_tasks)

    # Viloyat bosqichlaridan ortgan vaqt ham markazga qo'shiladi
    central_budget += remaining

    # 3-bosqich: boshqa binolardagi ko'chma darslar
    t = _run_phase("KO'CHMA-MARKAZ", phase_field_cen, central_budget * 0.2)
    central_budget = max(5.0, central_budget - t)
    _freeze(field_central)

    # 4-bosqich: boshqa binolardagi qolgan darslar (parchalanish jazosi shu yerda)
    _run_phase('MARKAZ', phase_central, central_budget)

    if not solution:
        return {
            'entries':  [],
            'stats':    {'status': solver.status_name(status_code)},
            'warnings': warnings + [
                f'OR-Tools yechim topolmadi: {solver.status_name(status_code)}. '
                'Band vaqtlar yoki sig\'im yetarli emasligini tekshiring.'
            ],
        }

    _p(96, "Xonalar biriktirilmoqda",
       "Har bir darsga mos xona tanlanmoqda (ko'chma mashg'ulotlarga xona "
       "biriktirilmaydi).")

    # ── 9. NATIJALARNI ScheduleEntry GA AYLANTIRISH ───────────────────────────
    # Xona band qilish (date, para_id) → {used room ids}
    used_rooms: defaultdict[tuple, set] = defaultdict(set)
    # Kompyuter xonasi topilmay, fallback xonaga tushgan fanlar (bir marta ogohlantirish uchun)
    no_computer_room_subjects: set[int] = set()

    entries: list[ScheduleEntry] = []
    total_placed = 0

    # ── NAZARIY / AMALIY BELGISINI QO'YISH ───────────────────────────────────
    # Auditoriya vazifasi solverga BITTA vazifa sifatida berilgan (nazariy +
    # amaliy soatlar birga). Endi uning joylashgan paralari VAQT BO'YICHA
    # tartiblanadi va birinchi `task.lec_paras` tasi "nazariy", qolgani
    # "amaliy" deb belgilanadi.
    #
    # Shu tufayli "avval nazariy, keyin amaliy" tartibi QURILISHI BO'YICHA
    # to'g'ri chiqadi — CP-SAT cheklovi kerak emas. Qo'lda tuzilgan haqiqiy
    # jadvalda ham aynan shunday: 84 (guruh × fan) juftlikning 84 tasida
    # global tartib saqlangan, 36 tasida esa nazariy bilan amaliy bir kunda
    # uchraydi (o'tish kunida "NA" naqshi) — bu yondashuv ikkalasini ham
    # tabiiy ravishda beradi.
    #
    # Vaqt tartibi `(sana, para.order)` bo'yicha — `para_id` bo'yicha EMAS,
    # chunki turli smenalarda para_id vaqt tartibiga mos kelishi kafolatlanmagan.
    lesson_type_by_key: dict[tuple, str] = {}
    _placed_by_task: defaultdict[int, list] = defaultdict(list)
    for (ti_, si_), placed_ in solution.items():
        if placed_ == 1:
            _placed_by_task[ti_].append(si_)

    for ti_, si_list in _placed_by_task.items():
        t_ = tasks[ti_]
        if t_.is_field or t_.lec_paras <= 0:
            continue          # ko'chma yoki sof amaliy — belgi o'zgarmaydi
        si_list.sort(key=lambda s_: (slots[s_].date,
                                     para_by_id[slots[s_].para_id].order))
        for pos, s_ in enumerate(si_list):
            lesson_type_by_key[(ti_, s_)] = (
                'lecture' if pos < t_.lec_paras else 'practice'
            )

    for (ti, si), placed in solution.items():
        if placed != 1:
            continue

        task = tasks[ti]
        slot = slots[si]
        # Shu KUNGA tegishli haqiqiy bino (guruh oy davomida turli binoda
        # bo'lishi mumkin — task darajasida emas, har bir joylashtirilgan
        # (vazifa, sana) juftligi uchun alohida, haqiqiy bug tuzatilgan).
        building_id = slot_building.get((ti, si))

        # Guruh talabalar soni
        group = Group.objects.filter(id=task.group_id).first()
        capacity = group.student_count if group else 1

        # Xona tanlash — quyidagi hollarda XONA UMUMAN TANLANMAYDI:
        #   - onlayn (Zoom) vazifalar
        #   - KO'CHMA MASHG'ULOT (`is_field`): tinglovchilar tashqariga chiqib
        #     amaliyot qiladi, ularga bino ichidan xona ajratish kerak emas
        #     (foydalanuvchi talabi)
        # Yakuniy dars turi — `lesson_type_by_key` da bo'lsa o'sha (auditoriya
        # vazifasi nazariy/amaliyga bo'lingan), aks holda vazifaning o'z turi
        # (ko'chma yoki sof nazariy/sof amaliy fanlar).
        final_lesson_type = lesson_type_by_key.get((ti, si), task.room_type)

        room = None
        if not task.is_online and not task.is_field:
            room = _select_room(
                building_id=building_id,
                lesson_type=final_lesson_type,
                min_capacity=capacity,
                used_room_ids=used_rooms[(slot.date, slot.para_id)],
                requires_computer_room=task.requires_computer_room,
            )
            if room:
                used_rooms[(slot.date, slot.para_id)].add(room.id)
                if (task.requires_computer_room and room.room_type != 'computer'
                        and task.subject_id not in no_computer_room_subjects):
                    no_computer_room_subjects.add(task.subject_id)
                    warnings.append(
                        f"Fan #{task.subject_id} kompyuter xonasini talab qiladi, lekin "
                        f"bino #{building_id}da bo'sh kompyuter xonasi topilmadi — "
                        "boshqa xonaga joylashtirildi."
                    )

        entries.append(ScheduleEntry(
            schedule=schedule,
            teacher_id=task.teacher_id,
            group_id=task.group_id,
            subject_id=task.subject_id or None,
            lesson_type=final_lesson_type,
            room=room,
            building_id=building_id,
            is_online=task.is_online,
            para_id=slot.para_id,
            date=slot.date,
        ))
        total_placed += 1

    stats = {
        'status':        solver.status_name(status_code),
        'tasks':         len(tasks),
        'total_paras':   sum(t.paras_needed for t in tasks),
        'placed_paras':  total_placed,
        'solve_time_s':  round(solver.wall_time, 2),
        'phases':        phase_log,
    }

    return {'entries': entries, 'stats': stats, 'warnings': warnings}
