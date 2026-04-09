from django.db import models


# ─────────────────────────────────────────────
#  YUKLAMA TAQSIMOTI  (Taqsimot Excel → DB)
# ─────────────────────────────────────────────

class LoadSheet(models.Model):
    """
    Kafedra mudiri yuklagan oylik taqsimot varag'i.
    Bitta yuklama = bitta department + bitta oy.
    Qayta yuklansa avvalgisi o'chiriladi.
    """
    department  = models.ForeignKey(
        'organizations.Department',
        on_delete=models.CASCADE,
        related_name='load_sheets',
        verbose_name="Kafedra"
    )
    month       = models.PositiveSmallIntegerField(verbose_name="Oy (1-12)")
    year        = models.PositiveIntegerField(verbose_name="Yil")
    uploaded_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_load_sheets',
        verbose_name="Yuklagan"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes       = models.TextField(blank=True, verbose_name="Izoh")

    class Meta:
        db_table = 'load_sheets'
        verbose_name = "Taqsimot varag'i"
        verbose_name_plural = "Taqsimot varaqlari"
        unique_together = ['department', 'month', 'year']
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.department} | {self.month}/{self.year}"


class TeacherLoad(models.Model):
    """
    O'qituvchining bir oylik yig'indi yuklamasi.
    Excel faylining bir T/r qatori + unga tegishli barcha modullar.
    """
    class Stavka(models.TextChoices):
        FULL    = '1.0',     "To'liq stavka (1.0)"
        HALF    = '0.5',     "Yarim stavka (0.5)"
        QUARTER = '0.25',    "Chorak stavka (0.25)"
        HOURLY  = 'soatbay', "Soatbay"
        VACANT  = 'vokant',  "Vokant (bo'sh o'rin)"

    load_sheet  = models.ForeignKey(
        LoadSheet,
        on_delete=models.CASCADE,
        related_name='teacher_loads',
        verbose_name="Taqsimot varag'i"
    )
    teacher     = models.ForeignKey(
        'scheduling.Teacher',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='load_records',
        verbose_name="O'qituvchi"
    )
    full_name   = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="F.I.Sh (Excel dan)",
        help_text="Teacher topilmasa ham Excel dagi ism saqlanadi"
    )
    position    = models.CharField(max_length=100, blank=True, verbose_name="Lavozim")
    stavka      = models.CharField(
        max_length=20,
        choices=Stavka.choices,
        default=Stavka.FULL,
        verbose_name="Stavka"
    )
    total_hours = models.PositiveSmallIntegerField(default=0, verbose_name="Jami soat (Hammasi)")

    class Meta:
        db_table = 'teacher_loads'
        verbose_name = "O'qituvchi oylik yuklamasi"
        verbose_name_plural = "O'qituvchilar oylik yuklamalari"

    def __str__(self):
        name = self.full_name or str(self.teacher)
        return f"{self.load_sheet} | {name} | {self.total_hours} soat"


class LoadDistribution(models.Model):
    """
    Taqsimotning eng mayda birligi:
    1 yozuv = 1 o'qituvchi + 1 fan/modul + 1 guruh + soat soni.
    Excel faylidagi bitta katak qiymatiga mos.
    """
    teacher_load       = models.ForeignKey(
        TeacherLoad,
        on_delete=models.CASCADE,
        related_name='distributions',
        verbose_name="O'qituvchi yuklamasi"
    )
    curriculum_subject = models.ForeignKey(
        'academic.CurriculumSubject',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='load_distributions',
        verbose_name="O'quv rejadagi fan"
    )
    module_name        = models.CharField(
        max_length=255,
        verbose_name="Modul nomi (Excel dan)",
        help_text="CurriculumSubject topilmasa ham saqlanadi"
    )
    group              = models.ForeignKey(
        'academic.Group',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='load_distributions',
        verbose_name="Guruh"
    )
    group_name         = models.CharField(
        max_length=100,
        verbose_name="Guruh nomi (Excel dan)",
        help_text="Group topilmasa ham saqlanadi"
    )
    hours              = models.PositiveSmallIntegerField(verbose_name="Soat soni")

    class Meta:
        db_table = 'load_distributions'
        verbose_name = "Taqsimot elementi"
        verbose_name_plural = "Taqsimot elementlari"
        ordering = ['teacher_load', 'module_name', 'group_name']

    def __str__(self):
        return (
            f"{self.teacher_load.full_name} | "
            f"{self.module_name} | "
            f"{self.group_name} | "
            f"{self.hours} soat"
        )


class Teacher(models.Model):
    user          = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='teacher_profile')
    organization  = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='teachers')
    subjects      = models.ManyToManyField('academic.Subject', blank=True, verbose_name="O'qita oladigan fanlar")
    personal_room = models.ForeignKey('organizations.Room', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Shaxsiy xona")
    is_active     = models.BooleanField(default=True)

    class Meta:
        db_table = 'teachers'
        verbose_name = "O'qituvchi"
        verbose_name_plural = "O'qituvchilar"

    def __str__(self):
        return str(self.user)

class TeacherBusyTime(models.Model):
    """
    O'qituvchining BAND vaqtlari.
    Kafedra mudiri kiritadi.
    Qolgan barcha vaqt = bo'sh.

    is_all_day=True bo'lsa, o'sha kunda hech qanday dars qo'yilmaydi.
    is_all_day=False bo'lsa, start_time..end_time oralig'i band hisoblanadi.
    """
    teacher    = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='busy_times')
    date       = models.DateField(verbose_name="Sana")
    is_all_day = models.BooleanField(
        default=False,
        verbose_name="Butun kun band",
        help_text="Belgilansa, o'sha kunda hech qanday para qo'yilmaydi"
    )
    start_time = models.TimeField(
        null=True, blank=True,
        verbose_name="Boshlanish vaqti",
        help_text="is_all_day=False bo'lganda to'ldirish shart"
    )
    end_time   = models.TimeField(
        null=True, blank=True,
        verbose_name="Tugash vaqti",
        help_text="is_all_day=False bo'lganda to'ldirish shart"
    )
    reason     = models.CharField(max_length=255, blank=True, verbose_name="Sabab")

    class Meta:
        db_table = 'teacher_busy_times'
        verbose_name = "Band vaqt"
        verbose_name_plural = "Band vaqtlar"
        ordering = ['date', 'start_time']

    def __str__(self):
        if self.is_all_day:
            return f"{self.teacher} | {self.date} | Butun kun"
        return (
            f"{self.teacher} | "
            f"{self.date} | "
            f"{self.start_time.strftime('%H:%M')}-"
            f"{self.end_time.strftime('%H:%M')}"
        )

    def is_conflict(self, date, para) -> bool:
        """
        Para vaqti band vaqt bilan to'qnashadimi?
        Butun kun band bo'lsa — har qanday para to'qnashadi.
        """
        if self.date != date:
            return False
        if self.is_all_day:
            return True
        if not self.start_time or not self.end_time:
            return False
        return (
            self.start_time <= para.start_time < self.end_time or
            self.start_time < para.end_time <= self.end_time
        )


class TeacherSubjectAssignment(models.Model):
    """
    O'qituvchi qaysi yo'nalishda
    qaysi fanlardan dars bera olishi.
    Kafedra mudiri belgilaydi.
    """
    teacher  = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='subject_assignments')
    major    = models.ForeignKey('academic.Major', on_delete=models.CASCADE, related_name='teacher_assignments')
    subjects = models.ManyToManyField('academic.Subject', related_name='teacher_assignments', verbose_name="Fanlar")

    class Meta:
        db_table = 'teacher_subject_assignments'
        verbose_name = "O'qituvchi fan biriktiruvi"
        verbose_name_plural = "O'qituvchi fan biriktiruvilari"
        unique_together = ['teacher', 'major']

    def __str__(self):
        return f"{self.teacher} → {self.major}"


class TeacherMonthlyLoad(models.Model):
    """
    O'qituvchining oylik soat yuklamasi.
    Kafedra mudiri har oy belgilaydi.
    Masalan: Alimov A → Maktab yo'nalishi → Mart → 14 soat
    """
    class Status(models.TextChoices):
        PENDING  = 'pending',  'Kutilmoqda'
        APPROVED = 'approved', 'Tasdiqlangan'

    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='monthly_loads')
    major   = models.ForeignKey('academic.Major', on_delete=models.CASCADE, related_name='monthly_loads')
    month   = models.PositiveSmallIntegerField(verbose_name="Oy (1-12)")
    year    = models.PositiveIntegerField(verbose_name="Yil")
    total_hours = models.PositiveSmallIntegerField(verbose_name="Oylik soat")
    status  = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    assigned_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, related_name='assigned_loads'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'teacher_monthly_loads'
        verbose_name = "Oylik yukla"
        verbose_name_plural = "Oylik yuklamalar"
        unique_together = ['teacher', 'major', 'month', 'year']

    def __str__(self):
        months = {
            1: 'Yanvar', 2: 'Fevral', 3: 'Mart',
            4: 'Aprel', 5: 'May', 6: 'Iyun',
            7: 'Iyul', 8: 'Avgust', 9: 'Sentabr',
            10: 'Oktabr', 11: 'Noyabr', 12: 'Dekabr'
        }
        return (
            f"{self.teacher} | "
            f"{self.major} | "
            f"{months.get(self.month)} {self.year} | "
            f"{self.total_hours} soat"
        )

    @property
    def total_paras(self):
        """Oylik para soni = soat ÷ 2"""
        return self.total_hours // 2


class Schedule(models.Model):
    """
    Oylik jadval.
    Masalan: 2026-yil Mart oyi jadvali.
    """
    class Status(models.TextChoices):
        DRAFT     = 'draft',     'Qoralama'
        PUBLISHED = 'published', 'Nashr etilgan'
        ARCHIVED  = 'archived',  'Arxivlangan'

    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='schedules')
    title        = models.CharField(max_length=255, verbose_name="Jadval nomi")
    month        = models.PositiveSmallIntegerField(verbose_name="Oy (1-12)")
    year         = models.PositiveIntegerField(verbose_name="Yil")
    date_from    = models.DateField(verbose_name="Boshlanish sanasi")
    date_to      = models.DateField(verbose_name="Tugash sanasi")
    status       = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    generated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='generated_schedules')
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'schedules'
        verbose_name = "Jadval"
        verbose_name_plural = "Jadvallar"
        unique_together = ['organization', 'month', 'year']

    def __str__(self):
        return f"{self.title} | {self.month}/{self.year} ({self.get_status_display()})"


class ScheduleEntry(models.Model):
    """
    Jadval elementi — bitta dars.
    Aniq sana va vaqt bilan.
    """
    schedule        = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='entries')
    teacher         = models.ForeignKey('scheduling.Teacher', on_delete=models.CASCADE, related_name='schedule_entries')
    group           = models.ForeignKey('academic.Group', on_delete=models.CASCADE, related_name='schedule_entries')
    subject         = models.ForeignKey('academic.Subject', on_delete=models.CASCADE, related_name='schedule_entries')
    lesson_type     = models.CharField(
        max_length=20,
        choices=[('lecture', 'Nazariy'), ('practice', 'Amaliy')]
    )
    room            = models.ForeignKey(
        'organizations.Room',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Xona"
    )
    building = models.ForeignKey(
        'organizations.Building',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Bino"
    )
    para            = models.ForeignKey('academic.Para', on_delete=models.CASCADE)
    date            = models.DateField(verbose_name="Dars sanasi")
    is_substituted  = models.BooleanField(default=False)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'schedule_entries'
        verbose_name = "Jadval elementi"
        verbose_name_plural = "Jadval elementlari"
        ordering = ['date', 'para__order']

    def __str__(self):
        return (
            f"{self.date} | "
            f"{self.group} | "
            f"{self.subject} | "
            f"{self.para} | "
            f"{self.room or self.building}"
        )


class Substitution(models.Model):
    """
    O'rinbosarlik — o'qituvchi kela olmasa
    boshqa o'qituvchi bilan almashtirish.
    """
    class Status(models.TextChoices):
        REQUESTED = 'requested', "So'ralgan"
        CONFIRMED = 'confirmed', 'Tasdiqlangan'
        CANCELLED = 'cancelled', 'Bekor qilingan'

    schedule_entry     = models.ForeignKey(ScheduleEntry, on_delete=models.CASCADE, related_name='substitutions')
    original_teacher   = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='original_substitutions')
    substitute_teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='substitute_substitutions')
    date               = models.DateField(verbose_name="Sana")
    reason             = models.TextField(blank=True, verbose_name="Sabab")
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    requested_by       = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'substitutions'
        verbose_name = "O'rinbosarlik"
        verbose_name_plural = "O'rinbosarliklar"

    def __str__(self):
        return f"{self.date} | {self.original_teacher} → {self.substitute_teacher}"


class AuditLog(models.Model):
    """
    Barcha o'zgarishlar logi.
    Kim, qachon, nima o'zgartirdi.
    """
    class Action(models.TextChoices):
        CREATE     = 'create',     'Yaratildi'
        UPDATE     = 'update',     'Tahrirlandi'
        DELETE     = 'delete',     "O'chirildi"
        GENERATE   = 'generate',   'Generatsiya'
        PUBLISH    = 'publish',    'Nashr etildi'
        APPROVE    = 'approve',    'Tasdiqlandi'
        REJECT     = 'reject',     'Rad etildi'
        SUBSTITUTE = 'substitute', "O'rinbosar"

    organization = models.ForeignKey('organizations.Organization', on_delete=models.SET_NULL, null=True)
    user         = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    action       = models.CharField(max_length=20, choices=Action.choices)
    model_name   = models.CharField(max_length=100)
    object_id    = models.PositiveIntegerField(null=True, blank=True)
    object_repr  = models.CharField(max_length=500, blank=True)
    changes      = models.JSONField(default=dict)
    timestamp    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        verbose_name = "Audit logi"
        verbose_name_plural = "Audit loglari"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['organization', 'timestamp']),
            models.Index(fields=['model_name', 'object_id']),
        ]

    def __str__(self):
        return f"[{self.timestamp:%d.%m.%Y %H:%M}] {self.user} | {self.get_action_display()} | {self.model_name}"