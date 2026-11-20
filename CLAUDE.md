# CLAUDE.md — SportEdu Jadval (backend)

Django 6 + DRF + JWT (SimpleJWT) + PostgreSQL + OR-Tools CP-SAT.
Virtual muhit: `venv/Scripts/python.exe` (Windows).

6 ta app: `accounts` (User + rol), `organizations` (Organization/Building/Room/Department),
`academic` (Major/Subject/Curriculum/Group/Shift/Para/GroupDayAssignment),
`scheduling` (Teacher/LoadSheet/Schedule/GroupSubject/LessonJournal/AuditLog + solver),
`reports` (modelsiz, faqat Excel/PDF export), `config` (project package).

Barcha API `/api/v1/` ostida. JWT: `/api/auth/login/`, `/api/auth/refresh/`.
Swagger: `/api/docs/`.

## Bog'liq repo va hujjatlar

Bu backend **frontend bilan juft** ishlaydi:

- **Frontend**: `D:/FrontEnd/Sportedu/SaaS Education ERP & Scheduling System`
  (React 19 + Vite + Ant Design 6, faqat JavaScript)
- **Qoidalar**: `D:/FrontEnd/Sportedu/SaaS Education ERP & Scheduling System/.claude/rules/`
  — barcha qoidalar **bitta joyda**, ikkala repo uchun. Backend uchun eng muhimlari:
  `backend.md`, `api.md`, `errors.md`, `backend-architecture.md`, `roles-permissions.md`,
  `schedule-generation.md`
- **Vault**: `D:/ObsidianVault/Sportedu/` — `_holat.md` dolzarb holatni ko'rsatadi

## Sessiya tartibi

1. Sessiya boshida `D:/ObsidianVault/Sportedu/_holat.md` ni o'qing.
2. Tegishli rule faylini (yuqoridagi yo'ldan) o'qing.
3. **Real kodni tekshiring** — `.md` xarita, haqiqat manbai emas. Mos kelmasa
   o'zgartirishni qo'llamang, farqni aytib so'rang.
4. Muhim ishdan keyin frontend repodagi `/save`, muhim qarordan keyin `/decision`.

## Eng ko'p takrorlangan tuzoqlar

1. **`http_method_names`** ViewSet darajasida `@action(methods=[...])` dan ustun —
   `'post'` yo'q bo'lsa action 405 qaytaradi (2 marta uchragan).
2. **`get_permissions()`** override qilingan ViewSet'da `@action(permission_classes=[...])`
   e'tiborsiz qoladi — yangi action'ni `get_permissions()` ga qo'shing.
3. **Pagination**: global `PAGE_SIZE=20`; `page_size_query_param` yoqilmasa frontend
   yuborgan `page_size=500` **jimgina** e'tiborsiz qoladi.
4. **`Meta.ordering`** bo'lmasa PostgreSQL'da qatorlar sahifalar orasida yo'qoladi.
5. **`transaction.savepoint()`** autocommit'da ishlamaydi — `with transaction.atomic():`
   ichida maxsus `Rollback` exception ishlating.

Batafsil: `.claude/rules/errors.md` (frontend repoda).

## Taqiqlar

- **`.env` ni o'qimang.** Ochiq parol topsangiz — darhol ayting.
- **`manage.py flush` / `sqlflush` / `rm -rf` / `git reset --hard` / `git push --force`** — yo'q.
- **Commit faqat so'ralganda**, foydalanuvchi nomidan (`BoastfulApex`), attribution qatorisiz.
- **`scheduling/solver.py` ni o'lchamasdan o'zgartirmang** — real sentabr 2026 ma'lumotida
  kamida 2–3 marta sinang (`schedule-generation.md` dagi test qoidalariga rioya qiling:
  bitta vaqtda bitta test, `{ ... } &` ishlatmang).

## Tekshirish

```bash
venv/Scripts/python.exe manage.py check
venv/Scripts/python.exe manage.py makemigrations --check --dry-run
venv/Scripts/python.exe manage.py test
```
