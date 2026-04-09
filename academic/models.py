from django.db import models


class Major(models.Model):
    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='majors')
    name         = models.CharField(max_length=255, verbose_name="Yo'nalish nomi")
    code         = models.CharField(max_length=50, verbose_name="Yo'nalish kodi")
    is_active    = models.BooleanField(default=True)

    class Meta:
        db_table = 'majors'
        verbose_name = "Ta'lim yo'nalishi"
        verbose_name_plural = "Ta'lim yo'nalishlari"
        unique_together = ['organization', 'code']

    def __str__(self):
        return f"{self.code} — {self.name}"


class Subject(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='subjects'
    )
    department   = models.ForeignKey(
        'organizations.Department',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Kafedra",
        related_name='subjects'
    )
    name = models.CharField(max_length=255, verbose_name="Fan nomi")
    code = models.CharField(max_length=50, verbose_name="Fan kodi")

    class Meta:
        db_table = 'subjects'
        verbose_name = "Fan"
        verbose_name_plural = "Fanlar"
        unique_together = ['organization', 'code']

    def __str__(self):
        return f"{self.name} ({self.code})"
    
    
class Curriculum(models.Model):
    """
    O'quv reja — yo'nalish uchun.
    Excel formatiga mos: kurs muddati, tinglovchilar, o'qish shakli.
    O'zgarganda arxivlanadi, yangi yaratiladi.
    """
    class Status(models.TextChoices):
        ACTIVE   = 'active',   'Faol'
        ARCHIVED = 'archived', 'Arxivlangan'

    class StudyForm(models.TextChoices):
        FULLTIME = 'fulltime', 'Kunduzgi (asosiy ishdan ajralgan holda)'
        PARTTIME = 'parttime', 'Sirtqi (asosiy ishdan ajralmagan holda)'
        DISTANCE = 'distance', 'Masofaviy'

    major          = models.ForeignKey(Major, on_delete=models.CASCADE, related_name='curriculums')
    name           = models.CharField(max_length=255, verbose_name="O'quv reja nomi")
    contingent     = models.CharField(
        max_length=255,
        verbose_name="Tinglovchilar kontingenti",
        blank=True,
        help_text="Masalan: Sport ta'lim muassasalarining trenerlari"
    )
    study_form     = models.CharField(
        max_length=20,
        choices=StudyForm.choices,
        default=StudyForm.FULLTIME,
        verbose_name="O'qish shakli"
    )
    duration_weeks = models.PositiveSmallIntegerField(
        default=4,
        verbose_name="Kurs muddati (hafta)"
    )
    total_hours    = models.PositiveSmallIntegerField(
        default=144,
        verbose_name="Jami soat"
    )
    status         = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'curriculums'
        verbose_name = "O'quv reja"
        verbose_name_plural = "O'quv rejalar"

    def __str__(self):
        return f"{self.major} | {self.name} | ({self.get_status_display()})"

    def archive(self):
        """O'quv rejani arxivlash"""
        self.status = self.Status.ARCHIVED
        self.save()
        

class CurriculumBlock(models.Model):
    """
    O'quv rejadagi blok — faqat guruhlovchi element.
    Kafedra endi blokka emas, har bir fanga biriktiriladi.
    """
    curriculum = models.ForeignKey(
        Curriculum, on_delete=models.CASCADE, related_name='blocks'
    )
    order = models.PositiveSmallIntegerField(verbose_name="Blok tartibi")
    name  = models.CharField(max_length=255, blank=True, default='', verbose_name="Blok nomi")

    class Meta:
        db_table = 'curriculum_blocks'
        verbose_name = "Blok"
        verbose_name_plural = "Bloklar"
        ordering = ['order']
        unique_together = ['curriculum', 'order']

    def __str__(self):
        return f"{self.curriculum.name} | {self.order}-blok: {self.name or '—'}"

    @property
    def total_hours(self):
        return sum(s.grand_total_hours for s in self.subjects.all())

    @property
    def lecture_hours(self):
        return sum(s.lecture_hours for s in self.subjects.all())

    @property
    def practice_hours(self):
        return sum(s.practice_hours for s in self.subjects.all())

    @property
    def field_hours(self):
        return sum(s.field_hours for s in self.subjects.all())

    @property
    def independent_hours(self):
        return sum(s.independent_hours for s in self.subjects.all())

    @property
    def total_paras(self):
        return sum(s.total_paras for s in self.subjects.all())


class CurriculumSubject(models.Model):
    """
    O'quv rejadagi fan — Excel formatiga to'liq mos.
    Har fan uchun 1 qator: nazariy, amaliy, ko'chma, mustaqil, haftalik taqsimot.
    """
    block      = models.ForeignKey(
        CurriculumBlock, on_delete=models.CASCADE, related_name='subjects'
    )
    subject    = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='curriculum_subjects'
    )
    department = models.ForeignKey(
        'organizations.Department',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Kafedra",
        related_name='curriculum_subjects',
        help_text="Shu fanni qaysi kafedra o'tishi"
    )
    order      = models.PositiveSmallIntegerField(
        verbose_name="Tartib raqami",
        default=1,
        help_text="Blok ichidagi tartib (1.1, 1.2, ...)"
    )

    # Soat turlari — Excel ustunlariga mos
    lecture_hours     = models.PositiveSmallIntegerField(default=0, verbose_name="Nazariy soat")
    practice_hours    = models.PositiveSmallIntegerField(default=0, verbose_name="Amaliy soat")
    field_hours       = models.PositiveSmallIntegerField(default=0, verbose_name="Ko'chma mashg'ulot soati")
    independent_hours = models.PositiveSmallIntegerField(default=0, verbose_name="Mustaqil tayyorgarlik soati")

    # Haftalik taqsimot — Excel I, II, III, IV ustunlariga mos
    week1_hours       = models.PositiveSmallIntegerField(default=0, verbose_name="I-hafta soati")
    week2_hours       = models.PositiveSmallIntegerField(default=0, verbose_name="II-hafta soati")
    week3_hours       = models.PositiveSmallIntegerField(default=0, verbose_name="III-hafta soati")
    week4_hours       = models.PositiveSmallIntegerField(default=0, verbose_name="IV-hafta soati")

    class Meta:
        db_table = 'curriculum_subjects'
        verbose_name = "Fan"
        verbose_name_plural = "Fanlar"
        ordering = ['order']
        unique_together = ['block', 'subject']

    def __str__(self):
        return (
            f"{self.block} | "
            f"{self.subject.name} | "
            f"{self.auditorium_hours} soat"
        )

    @property
    def auditorium_hours(self):
        """Auditoriya soati = nazariy + amaliy + ko'chma"""
        return self.lecture_hours + self.practice_hours + self.field_hours

    @property
    def grand_total_hours(self):
        """Jami soat = auditoriya + mustaqil"""
        return self.auditorium_hours + self.independent_hours

    @property
    def total_paras(self):
        """Auditoriya para soni = auditoriya soat ÷ 2"""
        return self.auditorium_hours // 2

    @property
    def weekly_total(self):
        """Haftalik soatlar yig'indisi (tekshirish uchun)"""
        return self.week1_hours + self.week2_hours + self.week3_hours + self.week4_hours

    
class Group(models.Model):
    class Month(models.IntegerChoices):
        YANVAR  = 1,  'Yanvar'
        FEVRAL  = 2,  'Fevral'
        MART    = 3,  'Mart'
        APREL   = 4,  'Aprel'
        MAY     = 5,  'May'
        IYUN    = 6,  'Iyun'
        IYUL    = 7,  'Iyul'
        AVGUST  = 8,  'Avgust'
        SENTABR = 9,  'Sentabr'
        OKTABR  = 10, 'Oktabr'
        NOYABR  = 11, 'Noyabr'
        DEKABR  = 12, 'Dekabr'

    organization  = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='groups'
    )
    major         = models.ForeignKey(
        Major,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Yo'nalish",
        related_name='groups'
    )
    name          = models.CharField(max_length=100, verbose_name="Guruh nomi")
    student_count = models.PositiveIntegerField(default=0, verbose_name="Talabalar soni")
    month         = models.IntegerField(choices=Month.choices, verbose_name="Oy", null=True, blank=True)
    year          = models.PositiveIntegerField(verbose_name="Yil", null=True, blank=True)
    start_date    = models.DateField(verbose_name="Boshlanish sanasi", null=True, blank=True)
    end_date      = models.DateField(verbose_name="Tugash sanasi", null=True, blank=True)
    is_active     = models.BooleanField(default=True)

    class Meta:
        db_table = 'groups'
        verbose_name = "Guruh"
        verbose_name_plural = "Guruhlar"
        unique_together = ['organization', 'name', 'month', 'year']

    def __str__(self):
        return f"{self.year} {self.get_month_display()} — {self.name}"
    

class Shift(models.Model):
    """
    Smena — admin o'zi yaratadi.
    Masalan: Ertalabki (08:00-14:00), Kunduzi (14:00-20:00)
    """
    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='shifts')
    name         = models.CharField(max_length=100, verbose_name="Smena nomi")
    start_time   = models.TimeField(verbose_name="Boshlanish vaqti")
    end_time     = models.TimeField(verbose_name="Tugash vaqti")
    is_active    = models.BooleanField(default=True)

    class Meta:
        db_table = 'shifts'
        verbose_name = "Smena"
        verbose_name_plural = "Smenalar"

    def __str__(self):
        return f"{self.name} ({self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')})"


class Para(models.Model):
    """
    Para — smena ichidagi dars bloki.
    Masalan: 1-para 08:30-10:00, 2-para 10:15-11:45
    """
    shift      = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name='paras')
    name       = models.CharField(max_length=50, verbose_name="Para nomi")
    order      = models.PositiveSmallIntegerField(verbose_name="Tartib")
    start_time = models.TimeField(verbose_name="Boshlanish vaqti")
    end_time   = models.TimeField(verbose_name="Tugash vaqti")
    is_active  = models.BooleanField(default=True)

    class Meta:
        db_table = 'paras'
        verbose_name = "Para"
        verbose_name_plural = "Paralar"
        ordering = ['order']
        unique_together = ['shift', 'order']

    def __str__(self):
        return f"{self.shift.name} | {self.name}: {self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')}"


class GroupAssignment(models.Model):
    """
    Guruhga smena va bino biriktirilishi.
    Jadval generatsiyadan OLDIN bo'lishi shart.
    Bu oylik — har oy o'zgarishi mumkin.
    """
    group    = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='assignments')
    shift    = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name='group_assignments')
    building = models.ForeignKey('organizations.Building', on_delete=models.CASCADE, related_name='group_assignments')
    month    = models.PositiveSmallIntegerField(verbose_name="Oy (1-12)")
    year     = models.PositiveIntegerField(verbose_name="Yil")

    class Meta:
        db_table = 'group_assignments'
        verbose_name = "Guruh biriktiruvi"
        verbose_name_plural = "Guruh biriktiruvilari"
        unique_together = ['group', 'month', 'year']

    def __str__(self):
        return f"{self.group} | {self.shift} | {self.building} | {self.month}/{self.year}"