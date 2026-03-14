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
    name         = models.CharField(max_length=255, verbose_name="Bino nomi")
    address      = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True)

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
