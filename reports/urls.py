from django.urls import path
from .views import ScheduleExcelExportView, SchedulePDFExportView

urlpatterns = [
    path(
        'reports/schedule/<int:schedule_id>/excel/',
        ScheduleExcelExportView.as_view(),
        name='schedule-excel-export',
    ),
    path(
        'reports/schedule/<int:schedule_id>/pdf/',
        SchedulePDFExportView.as_view(),
        name='schedule-pdf-export',
    ),
]
