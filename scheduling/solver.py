"""
OR-Tools CP-SAT asosida jadval generatsiya.

Manbalar:
  - LoadDistribution  → kim, qaysi fandan, qaysi guruhga, necha soat
  - Para              → kunning vaqt uyachalari (1-para, 2-para, ...)
  - GroupAssignment   → guruh qaysi smena + binoda
  - TeacherBusyTime   → o'qituvchi band sanalar/vaqtlar
  - Room              → xonalar (tur, sig'im)
  - CurriculumSubject → haftalik soat taqsimoti (week1..week4)

Chiqish:
  - list[ScheduleEntry] — DB ga yozilishga tayyor yozuvlar
"""

import datetime
import calendar
from dataclasses import dataclass, field
from collections import defaultdict

from ortools.sat.python import cp_model

from academic.models import Para, Group, CurriculumSubject
from organizations.models import Room
from .models import (
    Teacher, TeacherBusyTime, LoadDistribution,
    ScheduleEntry, Schedule,
)


# ──────────────────────────────────────────────────────────────────────────────
#  MA'LUMOT TUZILMALARI
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Task:
    """Bitta taqsimot yozuvidan yaratilgan vazifa."""
    dist_id:    int          # LoadDistribution.id
    teacher_id: int
    group_id:   int
    subject_id: int
    room_type:  str          # 'lecture' | 'practice' | 'field' | 'independent'
    hours:      int          # bajariladigan umumiy soat
    paras_needed: int        # hours // 2
    building_id:  int        # guruh biriktirilgan bino

    # Haftalik taqsimot (0 = cheklov yo'q)
    week_hours: list = field(default_factory=lambda: [0, 0, 0, 0])


@dataclass
class Slot:
    """Bitta vaqt uyachasi: sana + para."""
    date:     datetime.date
    para_id:  int
    week_idx: int   # 0..3


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
                 used_room_ids: set[int]) -> Room | None:
    """Bo'sh, mos xona topish."""
    qs = Room.objects.filter(
        building_id=building_id,
        is_active=True,
        capacity__gte=min_capacity,
    ).exclude(id__in=used_room_ids)

    if lesson_type in ('lecture',):
        qs = qs.filter(room_type__in=['lecture', 'seminar'])
    elif lesson_type in ('practice', 'field'):
        qs = qs.filter(room_type__in=['lab', 'seminar'])

    return qs.first()


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

    # ── 3. TAQSIMOT MA'LUMOTLARI (LoadDistribution) ───────────────────────────
    distributions = (
        LoadDistribution.objects
        .filter(
            teacher_load__load_sheet__department__organization=organization,
            teacher_load__load_sheet__month=month,
            teacher_load__load_sheet__year=year,
            teacher_load__teacher__isnull=False,   # faqat bog'langan o'qituvchilar
            group__isnull=False,                   # faqat bog'langan guruhlar
            hours__gt=0,
        )
        .select_related(
            'teacher_load__teacher__user',
            'curriculum_subject__subject',
            'group',
        )
    )

    if not distributions.exists():
        return {
            'entries': [],
            'stats': {},
            'warnings': [
                'LoadDistribution topilmadi. '
                'Taqsimot yuklangan va guruhlar bog\'langanmi?'
            ],
        }

    # ── 4. GURUH → SMENA + BINO + PARALAR ────────────────────────────────────
    from academic.models import GroupAssignment
    assignments = {
        ga.group_id: ga
        for ga in GroupAssignment.objects.filter(
            group__organization=organization,
            month=month,
            year=year,
        ).select_related('shift', 'building')
    }

    # ── 5. VAZIFALAR (Task) YARATISH ──────────────────────────────────────────
    tasks: list[Task] = []

    for dist in distributions:
        group_id   = dist.group_id
        teacher_id = dist.teacher_load.teacher_id
        hours      = dist.hours

        if hours < 2:
            continue

        ga = assignments.get(group_id)
        if ga is None:
            warnings.append(
                f"Guruh #{group_id} uchun smena/bino biriktirilmagan — o'tkazib yuborildi."
            )
            continue

        # Faqat shu smena paralarini ishlatamiz
        shift_paras = [p for p in all_paras if p.shift_id == ga.shift_id]
        if not shift_paras:
            warnings.append(f"Smena #{ga.shift_id} uchun paralar yo'q.")
            continue

        cs = dist.curriculum_subject
        lesson_type = _lesson_type_for_subject(cs)

        week_hours = [0, 0, 0, 0]
        if cs:
            week_hours = [
                cs.week1_hours or 0,
                cs.week2_hours or 0,
                cs.week3_hours or 0,
                cs.week4_hours or 0,
            ]

        tasks.append(Task(
            dist_id=dist.id,
            teacher_id=teacher_id,
            group_id=group_id,
            subject_id=dist.curriculum_subject.subject_id if cs else 0,
            room_type=lesson_type,
            hours=hours,
            paras_needed=hours // 2,
            building_id=ga.building_id,
            week_hours=week_hours,
        ))

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
            # O'qituvchi band bo'lsa o'tkazib yuborish
            if (slot.date, slot.para_id) in busy:
                continue
            x[ti, si] = model.new_bool_var(f'x_{ti}_{si}')

    # ── CONSTRAINT 1: Har vazifa kerakli para sonini olishi shart ─────────────
    for ti, task in enumerate(tasks):
        vars_ = [x[ti, si] for si in range(len(slots)) if (ti, si) in x]
        if vars_:
            model.add(sum(vars_) == task.paras_needed)
        else:
            warnings.append(
                f"Vazifa (teacher={task.teacher_id}, group={task.group_id}) "
                f"uchun mos slot topilmadi — o'tkazib yuborildi."
            )

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
    for ti, task in enumerate(tasks):
        for week_i, w_hours in enumerate(task.week_hours):
            if w_hours <= 0:
                continue
            w_paras = w_hours // 2
            week_vars = [
                x[ti, si]
                for si in range(len(slots))
                if (ti, si) in x and slots[si].week_idx == week_i
            ]
            if week_vars:
                model.add(sum(week_vars) == w_paras)

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

        # Xona tanlash
        room = _select_room(
            building_id=task.building_id,
            lesson_type=task.room_type,
            min_capacity=capacity,
            used_room_ids=used_rooms[(slot.date, slot.para_id)],
        )
        if room:
            used_rooms[(slot.date, slot.para_id)].add(room.id)

        entries.append(ScheduleEntry(
            schedule=schedule,
            teacher_id=task.teacher_id,
            group_id=task.group_id,
            subject_id=task.subject_id or None,
            lesson_type=task.room_type,
            room=room,
            building_id=task.building_id,
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
