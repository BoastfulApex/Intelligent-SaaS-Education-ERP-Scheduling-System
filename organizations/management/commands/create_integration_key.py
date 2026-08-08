"""KPI integratsiyasi uchun API kalit yaratadi.

Ishlatish:
    python manage.py create_integration_key --org 1 --name "KPI" \
        --scopes groups:read schedule:read

To'liq kalit FAQAT shu yerda, bir marta ko'rsatiladi — bazada uning
SHA-256 hash'i saqlanadi va asl qiymatni tiklab bo'lmaydi.
"""
from django.core.management.base import BaseCommand, CommandError

from organizations.models import IntegrationClient, Organization


class Command(BaseCommand):
    help = "KPI integratsiyasi uchun API kalit yaratadi"

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True,
                            help="Organization ID")
        parser.add_argument('--name', required=True,
                            help="Mijoz nomi, masalan 'KPI (EEMSportedu)'")
        parser.add_argument('--scopes', nargs='+', required=True,
                            help="groups:read schedule:read")

    def handle(self, *args, **opts):
        valid = {c[0] for c in IntegrationClient.SCOPE_CHOICES}
        bad = set(opts['scopes']) - valid
        if bad:
            raise CommandError(
                f"Noma'lum scope: {', '.join(sorted(bad))}. "
                f"Mavjudlari: {', '.join(sorted(valid))}"
            )
        try:
            org = Organization.objects.get(pk=opts['org'])
        except Organization.DoesNotExist:
            raise CommandError(f"Organization #{opts['org']} topilmadi.")

        client, full_key = IntegrationClient.generate(
            organization=org, name=opts['name'], scopes=opts['scopes'],
        )
        self.stdout.write(self.style.SUCCESS(
            f"\nKalit yaratildi: {client.name}  (tashkilot: {org.name})\n"
            f"Scope'lar: {', '.join(client.scopes)}\n"
        ))
        self.stdout.write(self.style.WARNING(
            "TO'LIQ KALIT (faqat hozir ko'rsatiladi, saqlab qo'ying):\n"
        ))
        self.stdout.write(f"    {full_key}\n")
        self.stdout.write(
            "\nKPI tomonida .env ga yozing:  LMS_API_KEY=<yuqoridagi kalit>\n"
        )
