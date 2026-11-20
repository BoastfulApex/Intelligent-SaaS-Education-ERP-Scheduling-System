"""
Yuklanadigan fayllarni tekshirish (Excel/CSV import oqimlari uchun).

Avval tekshiruv faqat `file.name.endswith(('.xlsx', '.xls'))` edi — ya'ni
FAQAT fayl nomi bo'yicha, hajm chegarasisiz. Django'ning
`DATA_UPLOAD_MAX_MEMORY_SIZE` sozlamasi fayl yuklashga **qo'llanilmaydi**,
shuning uchun 500 MB `.xlsx` yoki "zip bomb" (kichik arxiv, ochilganda
gigabaytlar) yuborilsa, pandas/openpyxl uni xotiraga o'qib serverni
bo'g'ib qo'yishi mumkin edi.

Fayl diskda saqlanmaydi va qaytarib berilmaydi (loyihada `FileField` yo'q),
shuning uchun HTML/SVG orqali XSS vektori yo'q — bu yerdagi asosiy maqsad
**DoS'ning oldini olish**.
"""
MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # 10 MB

# Fayl boshidagi "magic bytes" — kengaytma emas, haqiqiy tarkib bo'yicha.
_SIGNATURES = {
    '.xlsx': (b'PK\x03\x04',),                      # ZIP konteyner (OOXML)
    '.xls':  (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',  # OLE2 (eski Excel)
              b'\x09\x08'),                         # BIFF (juda eski .xls)
}


def validate_upload(file, allowed_ext=('.xlsx', '.xls'), max_bytes=MAX_UPLOAD_BYTES):
    """
    Yuklangan faylni tekshiradi.

    Qaytaradi: xato matni (o'zbekcha) yoki `None` — hammasi joyida bo'lsa.
    Faylni o'qigandan keyin ko'rsatkichni boshiga qaytaradi, shuning uchun
    chaqiruvchi kod `pd.read_excel(file)` ni bemalol davom ettira oladi.
    """
    name = (file.name or '').lower()

    ext = next((e for e in allowed_ext if name.endswith(e)), None)
    if ext is None:
        ruxsat = ', '.join(allowed_ext)
        return f'Faqat {ruxsat} fayl qabul qilinadi.'

    size = getattr(file, 'size', None)
    if size is not None and size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        return (f'Fayl hajmi {mb} MB dan oshmasligi kerak '
                f'(yuborilgani: {size / 1024 / 1024:.1f} MB).')

    expected = _SIGNATURES.get(ext)
    if expected:
        try:
            head = file.read(8)
            file.seek(0)
        except Exception:
            return "Faylni o'qib bo'lmadi."
        if not any(head.startswith(sig) for sig in expected):
            return (f'Fayl tarkibi {ext} formatiga mos kelmadi — '
                    'nomi o\'zgartirilgan boshqa fayl bo\'lishi mumkin.')

    return None
