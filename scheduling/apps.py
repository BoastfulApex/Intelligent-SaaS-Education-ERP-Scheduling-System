from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'scheduling'
    verbose_name = "Jadval"

    def ready(self):
        from . import audit
        audit.connect_all()
        self._fail_stale_generations()

    def _fail_stale_generations(self):
        # Generatsiya alohida daemon thread'da ishlaydi (`ScheduleViewSet.generate`)
        # — server/worker jarayoni qayta ishga tushsa (deploy, restart) bu thread
        # ham o'ladi, lekin bazadagi `gen_status='running'` yozuvi shu holicha
        # qolib ketardi (avval faqat 30 daqiqadan keyin `STALE_GEN_SECONDS` orqali
        # avtomatik aniqlanardi). Har bir qayta ishga tushishda oldingi jarayon
        # ISHONCH BILAN o'lgan bo'ladi (thread jarayon bilan birga tugaydi),
        # shuning uchun bu yerda darhol `failed`ga o'tkazish xavfsiz.
        from django.db.utils import OperationalError, ProgrammingError
        try:
            from .models import Schedule
            Schedule.objects.filter(gen_status=Schedule.GenStatus.RUNNING).update(
                gen_status=Schedule.GenStatus.FAILED,
                gen_step="Server qayta ishga tushirilgani sababli to'xtatildi",
            )
        except (OperationalError, ProgrammingError):
            pass