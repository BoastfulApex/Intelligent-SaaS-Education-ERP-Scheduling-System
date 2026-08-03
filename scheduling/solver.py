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

import datetime
import calendar
from dataclasses import dataclass, field
from collections import defaultdict

from ortools.sat.python import cp_model

from academic.models import (
    Para, Group, CurriculumSubject, GroupDayAssignment, DeliveryMode, Curriculum,
)
from organizations.models import Room
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
    dist_id:    int          # GroupSubject.id (traceability uchun)
    teacher_id: int
    group_id:   int
    subject_id: int
    room_type:  str          # 'lecture' | 'practice' | 'field' | 'independent'
    hours:      int          # bajariladigan umumiy soat
    paras_needed: int        # hours // 2
    group_start: datetime.date   # guruhning shu oydagi haqiqiy boshlanish sanasi
    group_end:   datetime.date   # guruhning shu oydagi haqiqiy tugash sanasi
    building_id:  int | None = None   # guruh biriktirilgan bino (onlaynda None)
    is_online:    bool = False        # Group.delivery_mode == 'online' — xona/bino kerak emas
    requires_computer_room: bool = False   # Subject.requires_computer_room (IT/AKT fani)

    # Haftalik taqsimot (0 = cheklov yo'q) — guruhning o'z group_start'idan hisoblanadi
    week_hours: list = field(default_factory=lambda: [0, 0, 0, 0])


@dataclass
class Slot:
    """Bitta vaqt uyachasi: sana + para."""
    date:     datetime.date
    para_id:  int
    week_idx: int   # 0..3


@dataclass
class ResolvedAssignment:
    """Bir guruh uchun shu davrda vakillik qiluvchi smena/bino/onlayn holati."""
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


def _resolve_group_assignments(organization,
                               date_from: datetime.date,
                               date_to: datetime.date) -> dict[int, ResolvedAssignment]:
    """
    Har bir guruh uchun berilgan davrdagi smena/bino/onlayn holatini aniqlaydi.

    Manba — `GroupDayAssignment` ("Guruh biriktirish" kalendari, kunlik yozuvlar).
    Eski `academic.models.GroupAssignment` (oylik) endi ISHLATILMAYDI — hech qanday
    frontend sahifasi unga yozmaydi (o'lik jadval edi), shuning uchun jadval
    generatsiyasi undan foydalansa har doim "smena/bino biriktirilmagan" berib
    o'tkazib yuborardi.

    Guruh uchun shu davrdagi ENG ERTA sanali yozuv vakillik qiladi — xuddi
    `curriculum_preview`dagi (`scheduling/views.py`) `first_da` naqshi bilan bir xil,
    shunda ikkala joy ham bir xil "oyning vakillik qiluvchi biriktiruvi" mantig'iga
    tayanadi.

    Guruh `delivery_mode='online'` bo'lsa — `building_id=None` bo'lishi kutiladi va
    `is_online=True` qaytariladi (bino talab qilinmaydi, faqat smena kerak).
    """
    groups_by_id = {
        g.id: g for g in Group.objects.filter(organization=organization)
    }

    first_by_group: dict[int, GroupDayAssignment] = {}
    day_assignments = (
        GroupDayAssignment.objects
        .filter(group__organization=organization, date__range=(date_from, date_to),
                shift__isnull=False)
        .select_related('shift', 'building')
        .order_by('date')
    )
    for da in day_assignments:
        if da.group_id not in first_by_group:
            first_by_group[da.group_id] = da

    result: dict[int, ResolvedAssignment] = {}
    for group_id, da in first_by_group.items():
        group = groups_by_id.get(group_id)
        is_online = bool(group and group.delivery_mode == DeliveryMode.ONLINE)
        result[group_id] = ResolvedAssignment(
            shift_id=da.shift_id,
            building_id=da.building_id,
            is_online=is_online,
        )
    return result


def _lesson_type_for_subject(cs: CurriculumSubject | None) -> str:
    """O'quv rejadan dars turini aniqlash."""
    if cs is None:
        return 'lecture'
    if cs.lecture_hours > 0:
        return 'lecture'
    if cs.practice_hours > 0:
        return 'practice'
    if cs.field_hours > 0:
        return 'field'
    return 'lecture'


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

    # ── 4. GURUH → SMENA + BINO + PARALAR ────────────────────────────────────
    assignments = _resolve_group_assignments(organization, date_from, date_to)

    # ── 5. VAZIFALAR (Task) YARATISH — GroupSubject (haqiqiy Taqsimot manbai) ──
    tasks: list[Task] = []
    unassigned_count = 0
    month_end_day = calendar.monthrange(year, month)[1]

    for group in groups:
        curriculum = Curriculum.get_active_for_date(
            group.major,
            target_date=datetime.date(year, month, month_end_day),
            delivery_mode=group.delivery_mode,
            queryset=Curriculum.objects.prefetch_related('blocks__subjects__subject'),
        )
        if not curriculum:
            warnings.append(
                f"Guruh #{group.id} ({group.name}) uchun faol o'quv reja topilmadi — "
                "o'tkazib yuborildi."
            )
            continue

        ga = assignments.get(group.id)
        if ga is None:
            warnings.append(
                f"Guruh #{group.id} uchun smena biriktirilmagan — o'tkazib yuborildi."
            )
            continue

        # Oflayn guruhga bino shart — onlaynga (Zoom) kerak emas
        if not ga.is_online and ga.building_id is None:
            warnings.append(
                f"Guruh #{group.id} (oflayn) uchun bino biriktirilmagan — o'tkazib yuborildi."
            )
            continue

        # Faqat shu smena paralarini ishlatamiz
        shift_paras = [p for p in all_paras if p.shift_id == ga.shift_id]
        if not shift_paras:
            warnings.append(f"Smena #{ga.shift_id} uchun paralar yo'q.")
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

        gs_by_cs = {
            gs.curriculum_subject_id: gs
            for gs in GroupSubject.objects.filter(
                group=group,
                curriculum_subject__block__curriculum=curriculum,
                teacher__isnull=False,
                is_vacant=False,
            ).select_related('teacher')
        }

        for block in curriculum.blocks.all():
            for cs in block.subjects.select_related('subject').all():
                gs = gs_by_cs.get(cs.id)
                if not gs:
                    unassigned_count += 1
                    continue

                hours = cs.auditorium_hours
                if hours < 2:
                    continue

                lesson_type = _lesson_type_for_subject(cs)
                requires_computer_room = bool(cs.subject and cs.subject.requires_computer_room)

                week_hours = [
                    cs.week1_hours or 0,
                    cs.week2_hours or 0,
                    cs.week3_hours or 0,
                    cs.week4_hours or 0,
                ]

                tasks.append(Task(
                    dist_id=gs.id,
                    teacher_id=gs.teacher_id,
                    group_id=group.id,
                    subject_id=cs.subject_id,
                    room_type=lesson_type,
                    hours=hours,
                    paras_needed=hours // 2,
                    group_start=g_start,
                    group_end=g_end,
                    building_id=ga.building_id,
                    is_online=ga.is_online,
                    requires_computer_room=requires_computer_room,
                    week_hours=week_hours,
                ))

    if unassigned_count:
        warnings.append(
            f"Jami {unassigned_count} ta fanga o'qituvchi biriktirilmagan yoki vakant "
            "deb belgilangan — jadvalga kiritilmadi."
        )

    if not tasks:
        return {
            'entries': [],
            'stats': {},
            'warnings': warnings + ['Hech qanday vazifa yaratilmadi.'],
        }

    # ── 6. SLOT YARATISH (sana × para) ───────────────────────────────────────
    # Har guruh o'z smenasidagi paralardan foydalanadi
    # Umumiy slot: barcha (sana, para_id) juftlar
    all_slot_keys: set[tuple] = set()
    for t in tasks:
        ga = assignments[t.group_id]
        shift_para_ids = [p.id for p in all_paras if p.shift_id == ga.shift_id]
        for d in working_days:
            for pid in shift_para_ids:
                all_slot_keys.add((d, pid))

    slots = [Slot(date=d, para_id=p, week_idx=_week_index(d, date_from))
             for (d, p) in sorted(all_slot_keys)]
    slot_index = {(s.date, s.para_id): i for i, s in enumerate(slots)}

    # ── 7. OR-TOOLS MODEL ─────────────────────────────────────────────────────
    model  = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers  = 4

    # x[task_i, slot_j] = 1 → task_i slot_j da joylashtirildi
    x = {}
    for ti, task in enumerate(tasks):
        ga = assignments[task.group_id]
        shift_para_ids = {p.id for p in all_paras if p.shift_id == ga.shift_id}

        busy = _teacher_busy_set(task.teacher_id, date_from, date_to, all_paras)

        for si, slot in enumerate(slots):
            # Faqat o'qituvchi smenasidagi paralar
            if slot.para_id not in shift_para_ids:
                continue
            # Faqat guruhning O'Z muddati ichidagi kunlar (har guruh alohida
            # boshlanish/tugash sanasiga ega bo'lishi mumkin — Group.start_date/end_date)
            if slot.date < task.group_start or slot.date > task.group_end:
                continue
            # O'qituvchi band bo'lsa o'tkazib yuborish
            if (slot.date, slot.para_id) in busy:
                continue
            x[ti, si] = model.new_bool_var(f'x_{ti}_{si}')

    # ── HAFTALIK KVOTALARNI OLDINDAN HISOBLASH (Constraint 1 va 4 uchun) ──────
    # Har ikkala cheklov ham izchil bo'lishi SHART: agar Constraint 4 allaqachon
    # bironta haftani (masalan kech boshlangan guruh uchun 4-hafta) qisqartirgan
    # bo'lsa, Constraint 1'ning UMUMIY talabi ham xuddi shu qisqartirilgan
    # summaga mos kelishi kerak — aks holda ikkalasi bir-biriga zid qat'iy
    # tenglik hosil qilib, butun modelni (BARCHA guruhlar uchun, chunki `x` bitta
    # umumiy CP-SAT modelida baham ko'riladi) INFEASIBLE qilib qo'yadi (haqiqiy
    # bug, tuzatilgan — .claude/rules/schedule-generation.md). Shuning uchun
    # haftalik "talab qilinadigan" miqdorlar bir marta hisoblanadi va ikkala
    # cheklov ham xuddi shu qiymatlardan foydalanadi.
    task_week_required: dict[int, dict[int, int]] = {}
    for ti, task in enumerate(tasks):
        week_required: dict[int, int] = {}
        for week_i, w_hours in enumerate(task.week_hours):
            if w_hours <= 0:
                continue
            w_paras = w_hours // 2
            week_vars = [
                x[ti, si]
                for si in range(len(slots))
                if (ti, si) in x and _week_index(slots[si].date, task.group_start) == week_i
            ]
            if not week_vars:
                continue
            required = min(w_paras, len(week_vars))
            if required < w_paras:
                warnings.append(
                    f"Guruh #{task.group_id} uchun {week_i + 1}-haftada yetarli kun/para "
                    f"yo'q ({w_paras} kerak, {required} joy bor) — qisman joylashtirildi."
                )
            week_required[week_i] = required
        task_week_required[ti] = week_required

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

        week_required = task_week_required[ti]
        if week_required:
            required = sum(week_required.values())
        else:
            required = min(task.paras_needed, len(vars_))
            if required < task.paras_needed:
                warnings.append(
                    f"Vazifa (teacher={task.teacher_id}, group={task.group_id}) uchun "
                    f"yetarli slot yo'q ({task.paras_needed} kerak, {required} joy bor) — "
                    "qisman joylashtirildi."
                )
        model.add(sum(vars_) <= required)

    # ── CONSTRAINT 2: O'qituvchi bir vaqtda faqat bir joyda ──────────────────
    teacher_slot: defaultdict[tuple, list] = defaultdict(list)
    for (ti, si), var in x.items():
        teacher_slot[(tasks[ti].teacher_id, si)].append(var)

    for vars_ in teacher_slot.values():
        if len(vars_) > 1:
            model.add(sum(vars_) <= 1)

    # ── CONSTRAINT 3: Guruh bir vaqtda faqat bir darsda ──────────────────────
    group_slot: defaultdict[tuple, list] = defaultdict(list)
    for (ti, si), var in x.items():
        group_slot[(tasks[ti].group_id, si)].append(var)

    for vars_ in group_slot.values():
        if len(vars_) > 1:
            model.add(sum(vars_) <= 1)

    # ── CONSTRAINT 4: Haftalik soat taqsimoti ─────────────────────────────────
    # Har bir guruhning "1-hafta"si o'zining group_start'idan hisoblanadi (global
    # `slots[si].week_idx` emas) — har guruh alohida boshlanish sanasiga ega
    # bo'lishi mumkin (haqiqiy bug, tuzatilgan). Qiymatlar yuqorida oldindan
    # hisoblangan `task_week_required`dan olinadi (Constraint 1 bilan izchillik).
    # Xuddi Constraint 1 kabi — `<=` (qat'iy tenglik emas), bir necha fan bir xil
    # slot pulini baham ko'rganda butun modelni bloklab qo'ymasligi uchun.
    for ti, task in enumerate(tasks):
        for week_i, required in task_week_required[ti].items():
            week_vars = [
                x[ti, si]
                for si in range(len(slots))
                if (ti, si) in x and _week_index(slots[si].date, task.group_start) == week_i
            ]
            model.add(sum(week_vars) <= required)

    # ── MAQSAD: Maksimal joylashtirilgan para soni ────────────────────────────
    model.maximize(sum(x.values()))

    # ── 8. YECHISH ────────────────────────────────────────────────────────────
    status_code = solver.solve(model)

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            'entries':  [],
            'stats':    {'status': solver.status_name(status_code)},
            'warnings': warnings + [
                f'OR-Tools yechim topolmadi: {solver.status_name(status_code)}. '
                'Band vaqtlar yoki sig\'im yetarli emasligini tekshiring.'
            ],
        }

    # ── 9. NATIJALARNI ScheduleEntry GA AYLANTIRISH ───────────────────────────
    # Xona band qilish (date, para_id) → {used room ids}
    used_rooms: defaultdict[tuple, set] = defaultdict(set)
    # Kompyuter xonasi topilmay, fallback xonaga tushgan fanlar (bir marta ogohlantirish uchun)
    no_computer_room_subjects: set[int] = set()

    entries: list[ScheduleEntry] = []
    total_placed = 0

    for (ti, si), var in x.items():
        if solver.value(var) != 1:
            continue

        task = tasks[ti]
        slot = slots[si]

        # Guruh talabalar soni
        group = Group.objects.filter(id=task.group_id).first()
        capacity = group.student_count if group else 1

        # Xona tanlash — onlayn vazifalar uchun umuman kerak emas (Zoom)
        room = None
        if not task.is_online:
            room = _select_room(
                building_id=task.building_id,
                lesson_type=task.room_type,
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
                        f"bino #{task.building_id}da bo'sh kompyuter xonasi topilmadi — "
                        "boshqa xonaga joylashtirildi."
                    )

        entries.append(ScheduleEntry(
            schedule=schedule,
            teacher_id=task.teacher_id,
            group_id=task.group_id,
            subject_id=task.subject_id or None,
            lesson_type=task.room_type,
            room=room,
            building_id=task.building_id,
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
    }

    return {'entries': entries, 'stats': stats, 'warnings': warnings}
