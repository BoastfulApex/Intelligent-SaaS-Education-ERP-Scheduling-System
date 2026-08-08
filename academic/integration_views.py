"""
KPI (EEMSportedu) tizimi uchun server-to-server eksport endpointlari.

Shartnoma: `INTEGRATION_LMS.md` (KPI repozitoriysida) — 5- va 5-B bo'limlar.
Bu yerdagi javob FORMATI o'sha hujjat bilan qat'iy bog'langan; o'zgartirsangiz
hujjatni ham yangilang, aks holda KPI tomoni buziladi.

Autentifikatsiya: `Authorization: Api-Key <prefix>.<secret>`
(`permissions.HasIntegrationScope` — batafsil izoh o'sha yerda).

Nega alohida fayl: bular oddiy CRUD ViewSet emas — tashqi tizim bilan
shartnoma. `views.py` ga aralashtirilsa, kimdir uni "oddiy" endpoint deb
o'ylab formatini o'zgartirib yuborishi mumkin.
"""
import datetime
import uuid

from django.db.models import Prefetch
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import Building
from permissions import HasIntegrationScope

from .models import DeliveryMode, Group, GroupDayAssignment, Para, Shift


def _bad(detail, code, status=400):
    return Response({'detail': detail, 'code': code}, status=status)


def _year_month(request):
    """`?year=&month=` ni o'qib tekshiradi. (xato_javobi, year, month) qaytaradi."""
    try:
        year = int(request.query_params.get('year', ''))
        month = int(request.query_params.get('month', ''))
    except (TypeError, ValueError):
        return _bad("year va month butun son bo'lishi shart.", 'invalid_params'), None, None
    if not (1 <= month <= 12):
        return _bad("month 1 dan 12 gacha bo'lishi kerak.", 'invalid_params'), None, None
    if not (2000 <= year <= 2100):
        return _bad("year noto'g'ri.", 'invalid_params'), None, None
    return None, year, month


class IntegrationGroupsAPIView(APIView):
    """
    GET /api/v1/integration/groups/?year=2026&month=9

    Shu oyda dars o'tadigan OFLAYN guruhlar ro'yxati.

    **Onlayn guruhlar qaytarilmaydi** — KPI yuz-ID orqali jismoniy davomatni
    qayd qiladi, Zoom orqali o'qiydigan guruhda esa lokatsiyaga kelish tushunchasi
    yo'q. Filtrni KPI tomonida emas, shu yerda qilamiz: manba tizim o'zi
    ortiqchasini yubormasligi kerak.
    """
    authentication_classes = []
    permission_classes = [HasIntegrationScope]
    required_scope = 'groups:read'
    throttle_scope = 'integration'

    def get(self, request):
        err, year, month = _year_month(request)
        if err:
            return err

        org = request.integration_client.organization
        qs = (Group.objects
              .filter(organization=org, year=year, month=month,
                      is_active=True)
              .exclude(delivery_mode=DeliveryMode.ONLINE)
              .select_related('major')
              .order_by('name'))

        results = [{
            'code': str(g.external_code),
            'name': g.name,
            'year': g.year,
            'month': g.month,
            'major': g.major.name if g.major else None,
            'start_date': g.start_date.isoformat() if g.start_date else None,
            'end_date': g.end_date.isoformat() if g.end_date else None,
            'delivery_mode': g.delivery_mode,
            'student_count': g.student_count,
        } for g in qs]

        return Response({'count': len(results), 'results': results})


class IntegrationDayAssignmentsAPIView(APIView):
    """
    GET /api/v1/integration/day-assignments/?year=2026&month=9

    Guruhlarning KUNLIK smena + bino biriktiruvi, hamda ular ishlatadigan
    smenalar (paralari bilan) va binolar.

    Nega uchalasi bitta javobda: KPI tomonida import tartibi qat'iy —
    avval smena/bino, keyin biriktiruv. Uch alohida so'rov bo'lsa, ular
    orasida ma'lumot o'zgarib qolishi mumkin (masalan admin ayni damda
    yangi smena qo'shsa), natijada biriktiruv mavjud bo'lmagan smenaga
    ishora qilardi.
    """
    authentication_classes = []
    permission_classes = [HasIntegrationScope]
    required_scope = 'schedule:read'
    throttle_scope = 'integration'

    def get(self, request):
        err, year, month = _year_month(request)
        if err:
            return err

        org = request.integration_client.organization

        # Onlayn guruhlar bu yerda ham chiqarib tashlanadi — `groups`
        # endpointi bilan izchil bo'lishi shart, aks holda KPI'da topilmagan
        # guruh uchun biriktiruvlar "o'tkazib yuborildi" bo'lib hisoblanardi.
        groups = (Group.objects
                  .filter(organization=org, year=year, month=month,
                          is_active=True)
                  .exclude(delivery_mode=DeliveryMode.ONLINE))
        group_code = {g.id: str(g.external_code) for g in groups}

        assignments = (GroupDayAssignment.objects
                       .filter(group_id__in=group_code.keys(),
                               date__year=year, date__month=month)
                       .select_related('shift', 'building')
                       .order_by('date', 'group_id'))

        rows = []
        shift_ids, building_ids = set(), set()
        for a in assignments:
            rows.append({
                'group_code': group_code[a.group_id],
                'date': a.date.isoformat(),
                'shift_code': str(a.shift.external_code) if a.shift else None,
                'building_code': (str(a.building.external_code)
                                  if a.building else None),
            })
            if a.shift_id:
                shift_ids.add(a.shift_id)
            if a.building_id:
                building_ids.add(a.building_id)

        # Faqat HAQIQATAN ishlatilgan smena/binolar yuboriladi — butun
        # ro'yxat emas. Sabab: KPI tomonida har bir smena `Smena` +
        # `SmenaSlot` yaratadi, ishlatilmaganlari esa u yerda chalkash
        # bo'sh yozuv bo'lib qolardi.
        paras = Para.objects.filter(shift_id__in=shift_ids).order_by('order')
        paras_by_shift = {}
        for p in paras:
            paras_by_shift.setdefault(p.shift_id, []).append({
                'order': p.order,
                'name': p.name,
                'start_time': p.start_time.strftime('%H:%M'),
                'end_time': p.end_time.strftime('%H:%M'),
            })

        shifts = [{
            'code': str(s.external_code),
            'name': s.name,
            'paras': paras_by_shift.get(s.id, []),
        } for s in Shift.objects.filter(id__in=shift_ids).order_by('name')]

        buildings = [{
            'code': str(b.external_code),
            'name': b.name,
            'address': b.address or '',
            'is_regional': b.is_regional,
        } for b in Building.objects.filter(id__in=building_ids).order_by('name')]

        return Response({
            'shifts': shifts,
            'buildings': buildings,
            'assignments': rows,
        })
