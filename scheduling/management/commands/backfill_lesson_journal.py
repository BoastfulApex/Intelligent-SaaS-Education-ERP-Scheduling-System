"""
Bir martalik backfill — `_sync_lesson_journal` funksiyasi qo'shilishidan
OLDIN generatsiya qilingan jadvallar (`Schedule.generate` orqali yaratilgan
`ScheduleEntry`lar) uchun `LessonJournal` yozuvlarini orqaga qarab to'ldiradi.

Nega kerak: `_sync_lesson_journal` faqat YANGI generatsiya paytida
chaqiriladi (`ScheduleViewSet.generate`), mavjud `ScheduleEntry`lar uchun
avtomatik ishlamaydi. Shuning uchun bu funksiya qo'shilishidan oldin
yaratilgan jadvallarda o'qituvchi jurnalida (`/my-today`) hech narsa
ko'rinmaydi — bu haqiqiy production hodisasi (sentabr jadvali, #52).

Xavfsiz — mavjud `LessonJournal` yozuvlarini o'zgartirmaydi (faqat
yetishmaganlarini yaratadi), bir necha marta ishga tushirish mumkin.

Ishlatish:
    python manage.py backfill_lesson_journal
    python manage.py backfill_lesson_journal --schedule-id 52
"""
from django.core.management.base import BaseCommand

from scheduling.models import LessonJournal, ScheduleEntry
from scheduling.views import _sync_lesson_journal


class Command(BaseCommand):
    help = ("Mavjud ScheduleEntry yozuvlari uchun LessonJournal'ni orqaga "
            "qarab to'ldiradi (yangi generatsiya bo'lmasa ham).")

    def add_arguments(self, parser):
        parser.add_argument('--schedule-id', type=int, default=None,
                            help="Faqat shu jadval uchun (bo'sh — barchasi)")

    def handle(self, *args, **opts):
        qs = ScheduleEntry.objects.filter(teacher__isnull=False)
        if opts['schedule_id']:
            qs = qs.filter(schedule_id=opts['schedule_id'])

        entries = list(qs.only('id', 'teacher_id', 'group_id', 'subject_id',
                               'para_id', 'date', 'lesson_type'))
        before = LessonJournal.objects.count()
        self.stdout.write(f"{len(entries)} ta ScheduleEntry tekshirilmoqda...")

        _sync_lesson_journal(entries)

        after = LessonJournal.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Tayyor. LessonJournal: {before} -> {after} "
            f"({after - before} ta yangi yaratildi)."
        ))
