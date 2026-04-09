from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from .models import User
from .serializers import UserSerializer, UserCreateSerializer, ChangePasswordSerializer
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from permissions import IsOrgAdmin
import pandas as pd
import re


class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOrgAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['role', 'is_active']
    search_fields = ['username', 'first_name', 'last_name', 'email']

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_serializer_context(self):
        """Request ni serializer'ga uzatish (rol validatsiyasi uchun)."""
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.SUPER_ADMIN:
            return User.objects.all()
        return User.objects.filter(organization=user.organization)

    def perform_create(self, serializer):
        """
        Yangi foydalanuvchi yaratish:
          - super_admin → request da kelgan organization ishlatiladi
          - org_admin   → MAJBURAN o'z tashkiloti o'rnatiladi (boshqa org ga yarata olmaydi)
        """
        user = self.request.user
        if user.role == User.Role.SUPER_ADMIN:
            serializer.save()
        else:
            serializer.save(organization=user.organization)

    def perform_update(self, serializer):
        """
        Tahrirlashda ham tashkilotni o'zgartira olmaslik:
          - org_admin o'z tashkilotini o'zgartira olmaydi
        """
        user = self.request.user
        if user.role != User.Role.SUPER_ADMIN:
            serializer.save(organization=user.organization)
        else:
            serializer.save()

    @action(detail=False, methods=['get'], url_path='me',
            permission_classes=[IsAuthenticated])
    def me(self, request):
        """Joriy foydalanuvchi ma'lumotlari"""
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=['post'], url_path='bulk-create-teachers',
            permission_classes=[IsOrgAdmin])
    def bulk_create_teachers(self, request):
        """
        POST /api/v1/users/bulk-create-teachers/
        Bir vaqtda ko'p o'qituvchi (User + Teacher profil) yaratish.

        Body:
        {
          "teachers": [
            {
              "last_name":  "Aliyev",
              "first_name": "Vohid",
              "username":   "v.aliyev",        ← ixtiyoriy, auto-yasaladi
              "password":   "Parol1234",
              "phone":      "+998901234567",   ← ixtiyoriy
              "email":      "..."              ← ixtiyoriy
            },
            ...
          ]
        }
        Javob: { created: [...], errors: [...] }
        """
        from scheduling.models import Teacher

        org      = request.user.organization
        teachers = request.data.get('teachers', [])
        if not teachers:
            return Response({'error': '"teachers" ro\'yxati bo\'sh'}, status=400)

        created = []
        errors  = []

        for i, item in enumerate(teachers):
            last_name  = (item.get('last_name')  or '').strip()
            first_name = (item.get('first_name') or '').strip()
            password   = (item.get('password')   or '').strip()
            phone      = (item.get('phone')      or '').strip()
            email      = (item.get('email')      or '').strip()

            if not last_name or not password:
                errors.append({
                    'row': i + 1,
                    'error': 'Familiya va parol majburiy',
                    'data': item,
                })
                continue

            # Username: avtomatik — familiya.ism kichik harf
            username = item.get('username', '').strip()
            if not username:
                base = f"{last_name.lower()}.{first_name[0].lower()}" if first_name else last_name.lower()
                base = base.replace(' ', '_').replace("'", '').replace('ʻ', '').replace('ʼ', '')
                username = base
                # Noyoblik
                counter = 2
                while User.objects.filter(username=username).exists():
                    username = f"{base}{counter}"
                    counter += 1

            if User.objects.filter(username=username).exists():
                errors.append({
                    'row': i + 1,
                    'error': f'"{username}" username allaqachon mavjud',
                    'data': item,
                })
                continue

            try:
                user = User(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=phone,
                    role=User.Role.TEACHER,
                    organization=org,
                )
                user.set_password(password)
                user.save()

                teacher = Teacher.objects.create(
                    user=user,
                    organization=org,
                )
                created.append({
                    'row':        i + 1,
                    'user_id':    user.id,
                    'teacher_id': teacher.id,
                    'username':   username,
                    'full_name':  f"{last_name} {first_name}".strip(),
                })
            except Exception as e:
                errors.append({'row': i + 1, 'error': str(e), 'data': item})

        return Response({
            'success': len(errors) == 0,
            'message': f"{len(created)} ta o'qituvchi yaratildi"
                       + (f", {len(errors)} ta xato" if errors else ''),
            'created': created,
            'errors':  errors,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='upload-teachers',
            permission_classes=[IsOrgAdmin],
            parser_classes=[MultiPartParser, FormParser])
    def upload_teachers(self, request):
        """
        POST /api/v1/users/upload-teachers/
        Excel yoki CSV fayl orqali o'qituvchilarni import qilish.

        Fayl formati (istalgan ustun tartibi, sarlavha 1-qatorda):
          Familiya | Ism
          Aliyev   | Vohid
          Karimov  | Jasur

        Qaytaradi:
          { created: [...], skipped: [...], errors: [...] }
        """
        from scheduling.models import Teacher

        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'Fayl yuklanmadi'}, status=400)
        if not file.name.endswith(('.xlsx', '.xls', '.csv')):
            return Response({'error': 'Faqat .xlsx, .xls yoki .csv fayl'}, status=400)

        # Faylni o'qish — sarlavhasiz ham bo'lishi mumkin, shuning uchun header=None sinab ko'ramiz
        try:
            if file.name.endswith('.csv'):
                df_raw = pd.read_csv(file, header=None, dtype=str)
            else:
                df_raw = pd.read_excel(file, header=None, dtype=str)
        except Exception as e:
            return Response({'error': f'Faylni o\'qishda xato: {e}'}, status=400)

        # F.I.Sh yoki "Familiya" ustunini qidirish
        # Sarlavha qatori bo'lmasa ham ishlasin:
        # 1. Birinchi qatorda sarlavha bor-yo'qligini aniqlash
        NAME_HINTS = ['f.i.sh', 'fish', 'famil', 'professor', 'o\'qituv',
                      'ism', 'name', 'last', 'surname', 'фами']

        def _is_header(cell):
            s = str(cell).strip().lower()
            return any(h in s for h in NAME_HINTS) or re.search(r'[a-zA-Zа-яА-Я]{4,}', s) is not None

        # 1-qator sarlavha bo'lsa header=0, bo'lmasa header=None
        first_row = df_raw.iloc[0].fillna('').astype(str).tolist()
        has_header = any(_is_header(c) for c in first_row)

        if has_header:
            df = df_raw.copy()
            df.columns = [str(c).strip() for c in df.iloc[0]]
            df = df.iloc[1:].reset_index(drop=True)
        else:
            df = df_raw.copy()
            df.columns = [f'col{i}' for i in range(len(df.columns))]

        df = df.fillna('').astype(str)

        # F.I.Sh ustunini topish
        def find_col(keywords):
            for col in df.columns:
                low = col.lower()
                if any(k in low for k in keywords):
                    return col
            return None

        # "Professor-o'qituvchilarining F.I.Sh" kabi sarlavhani ham ushlaydi
        fullname_col = find_col(['f.i.sh', 'fish', 'professor', 'o\'qituv', 'teacher'])
        last_col     = find_col(['famil', 'last', 'surname', 'фамил']) if not fullname_col else None
        first_col    = find_col(['ism', 'first', 'имя'])               if not fullname_col else None

        # Hech narsa topilmasa — birinchi ustun to'liq ism
        if not fullname_col and not last_col:
            fullname_col = df.columns[0]

        org     = request.user.organization
        created = []
        skipped = []
        errors  = []

        import random, string
        def _make_password():
            chars = string.ascii_letters + string.digits
            return ''.join(random.choices(chars, k=8))

        def _make_username(last, initials):
            """pulatov.j — noyob bo'lmaguncha raqam qo'shiladi."""
            clean = lambda s: re.sub(r'[^a-z0-9]', '',
                s.lower()
                 .replace('ʻ','').replace('ʼ','').replace("'",'')
                 .replace('ğ','g').replace('ş','s').replace('ç','c')
                 .replace('ı','i').replace('ö','o').replace('ü','u')
            )
            l = clean(last)
            # initials = "J.A." → birinchi harf "j"
            first_char = ''
            if initials:
                m = re.search(r'[a-zA-ZА-Яа-яёЁ]', initials)
                if m:
                    first_char = clean(m.group())[:1]
            base = f"{l}.{first_char}" if first_char else l
            uname, n = base, 2
            while User.objects.filter(username=uname).exists():
                uname = f"{base}{n}"; n += 1
            return uname

        def _parse_fullname(raw):
            """
            "Pulatov J.A."   → ('Pulatov', 'J.A.')
            "Hayitov O.E."   → ('Hayitov', 'O.E.')
            "Arribaev Q"     → ('Arribaev', 'Q')
            "Aliyev Vohid"   → ('Aliyev', 'Vohid')
            "ALIYEV VOHID"   → ('Aliyev', 'Vohid')
            """
            raw = raw.strip()
            if not raw or raw.lower() in ('nan', 'none', ''):
                return None, None
            parts = raw.split(None, 1)
            last  = parts[0].capitalize()
            first = parts[1].strip() if len(parts) > 1 else ''
            return last, first

        for idx, row in df.iterrows():
            # To'liq ism ustunidan olish
            if fullname_col:
                raw_val    = str(row.get(fullname_col, '')).strip()
                last_name, first_name = _parse_fullname(raw_val)
            else:
                last_name  = str(row.get(last_col,  '')).strip().capitalize()
                first_name = str(row.get(first_col, '')).strip() if first_col else ''

            if not last_name or last_name.lower() in ('nan', 'none', ''):
                continue

            # Allaqachon mavjudmi?
            exists = User.objects.filter(
                last_name__iexact=last_name,
                first_name__iexact=first_name,
                organization=org,
                role=User.Role.TEACHER,
            ).exists()
            if exists:
                skipped.append({'last_name': last_name, 'first_name': first_name,
                                'reason': 'Allaqachon mavjud'})
                continue

            password = _make_password()
            username = _make_username(last_name, first_name)

            try:
                user = User(
                    username=username,
                    last_name=last_name,
                    first_name=first_name,
                    role=User.Role.TEACHER,
                    organization=org,
                )
                user.set_password(password)
                user.save()
                Teacher.objects.create(user=user, organization=org)
                created.append({
                    'last_name':  last_name,
                    'first_name': first_name,
                    'username':   username,
                    'password':   password,
                })
            except Exception as e:
                errors.append({'last_name': last_name, 'first_name': first_name, 'error': str(e)})

        return Response({
            'success': True,
            'message': (f"{len(created)} ta o'qituvchi qo'shildi"
                        + (f", {len(skipped)} ta o'tkazib yuborildi" if skipped else '')
                        + (f", {len(errors)} ta xato"                if errors  else '')),
            'created': created,
            'skipped': skipped,
            'errors':  errors,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='change-password',
            permission_classes=[IsAuthenticated])
    def change_password(self, request):
        """Parol o'zgartirish"""
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {'error': 'Eski parol noto\'g\'ri'},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        return Response({'message': 'Parol muvaffaqiyatli o\'zgartirildi'})