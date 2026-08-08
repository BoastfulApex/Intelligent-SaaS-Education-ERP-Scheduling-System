import uuid

from django.db import models


class Organization(models.Model):
    name       = models.CharField(max_length=255, verbose_name="Tashkilot nomi")
    slug       = models.SlugField(unique=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organizations'
        verbose_name = "Tashkilot"
        verbose_name_plural = "Tashkilotlar"

    def __str__(self):
        return self.name


class Building(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='buildings')
    # KPI tizimi bilan bog'lash uchun barqaror tashqi identifikator.
    # Nega UUID, oddiy `id` emas: `id` faqat SHU bazada ma'noli — baza qayta
    # tiklansa yoki boshqa tashkilot qo'shilsa raqamlar ustma-ust tushishi
    # mumkin. UUID esa global unikal va o'zgarmaydi.
    external_code = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True,
        verbose_name="Tashqi kod (integratsiya)"
    )
    name         = models.CharField(max_length=255, verbose_name="Bino nomi")
    address      = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True)
    # Viloyatda joylashgan lokatsiya — o'qituvchilar bu yerga komandirovkaga yuboriladi.
    # Jadval generatsiyasida shu binodagi darslar imkon qadar KAM o'qituvchi-kun bilan
    # (har bir o'qituvchining darslari zich, ketma-ket kunlarga to'plangan holda)
    # joylashtiriladi — bir vaqtda viloyatda minimal o'qituvchi bo'lishi uchun.
    is_regional  = models.BooleanField(default=False, verbose_name="Viloyatda joylashgan")

    class Meta:
        db_table = 'buildings'
        verbose_name = "Bino"
        verbose_name_plural = "Binolar"

    def __str__(self):
        return f"{self.name} ({self.organization})"


class Room(models.Model):
    class RoomType(models.TextChoices):
        LECTURE = 'lecture', "Ma'ruza zali"
        LAB     = 'lab',     'Laboratoriya'
        SEMINAR = 'seminar', 'Seminar xonasi'
        GYM      = 'gym',      'Sport zal'
        COMPUTER = 'computer', 'Kompyuter xonasi'

    building  = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='rooms')
    name      = models.CharField(max_length=100, verbose_name="Xona nomi")
    room_type = models.CharField(max_length=20, choices=RoomType.choices, default=RoomType.LECTURE)
    capacity  = models.PositiveIntegerField(verbose_name="Sig'im")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'rooms'
        verbose_name = "Xona"
        verbose_name_plural = "Xonalar"
        unique_together = ['building', 'name']

    def __str__(self):
        return f"{self.name} | {self.get_room_type_display()} | {self.capacity} o'rin"
    

class Department(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='departments'
    )
    name      = models.CharField(max_length=255, verbose_name="Kafedra nomi")
    order     = models.PositiveSmallIntegerField(verbose_name="Blok tartibi")
    manager   = models.OneToOneField(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Kafedra mudiri",
        related_name='managed_department'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'departments'
        verbose_name = "Kafedra (Blok)"
        verbose_name_plural = "Kafedralar (Bloklar)"
        ordering = ['order']
        unique_together = ['organization', 'order']

    def __str__(self):
        return f"{self.order}-blok: {self.name}"


class Position(models.Model):
    """
    Lavozim (masalan "Professor", "Dotsent", "Katta o'qituvchi") — ro'yxatni
    faqat org_admin(+) boshqaradi, kafedra mudiri esa o'qituvchi profilida
    shu ro'yxatdan tanlaydi (`Teacher.position`). `TeacherLoad.position`dan
    (Excel taqsimot yuklashda erkin matn ustuni) farqli — bu aniq, tashkilot
    darajasida boshqariladigan ro'yxat.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='positions'
    )
    name      = models.CharField(max_length=100, verbose_name="Lavozim nomi")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'positions'
        verbose_name = "Lavozim"
        verbose_name_plural = "Lavozimlar"
        ordering = ['name']
        unique_together = ['organization', 'name']

    def __str__(self):
        return self.name


class IntegrationClient(models.Model):
    """
    Tashqi tizim (KPI — EEMSportedu) bilan server-to-server aloqa uchun API kalit.

    Kalit formati:  <prefix>.<secret>
      - prefix — bazada OCHIQ saqlanadi, kalitni TOPISH uchun (indekslangan)
      - secret — bazada FAQAT SHA-256 hash ko'rinishida saqlanadi

    Nega foydalanuvchi JWT'si emas: JWT 8 soatda tugaydi va aniq bir odamga
    bog'langan — o'sha odam ishdan ketsa integratsiya to'xtaydi. API kalit esa
    TIZIMGA tegishli, muddatsiz va faqat kerakli scope'ga ega.

    Nega to'liq kalit saqlanmaydi: baza dumpi sizib chiqsa (backup, xato logi),
    hujumchi kalitlarni o'qiy olmasligi kerak. Hash'dan asl kalitni tiklab
    bo'lmaydi.
    """
    SCOPE_CHOICES = [
        ('groups:read', "Guruhlarni o'qish"),
        ('schedule:read', "Jadval/biriktiruvlarni o'qish"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='integration_clients'
    )
    name       = models.CharField(max_length=100, verbose_name="Nomi")
    key_prefix = models.CharField(max_length=12, unique=True, db_index=True)
    key_hash   = models.CharField(max_length=64)
    scopes     = models.JSONField(default=list, blank=True)
    is_active  = models.BooleanField(default=True)
    last_used  = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'integration_clients'
        verbose_name = "Integratsiya mijozi"
        verbose_name_plural = "Integratsiya mijozlari"

    def __str__(self):
        return f"{self.name} ({self.key_prefix}…)"

    @staticmethod
    def hash_secret(secret: str) -> str:
        import hashlib
        return hashlib.sha256(secret.encode()).hexdigest()

    @classmethod
    def generate(cls, organization, name, scopes):
        """Yangi kalit yaratadi. To'liq kalitni FAQAT shu yerda qaytaradi —
        keyin uni hech qayerdan tiklab bo'lmaydi."""
        import secrets
        prefix = secrets.token_hex(4)          # 8 belgi
        secret = secrets.token_urlsafe(36)     # ~48 belgi
        obj = cls.objects.create(
            organization=organization, name=name, scopes=list(scopes),
            key_prefix=prefix, key_hash=cls.hash_secret(secret),
        )
        return obj, f"{prefix}.{secret}"

    def has_scope(self, scope: str) -> bool:
        return scope in (self.scopes or [])
