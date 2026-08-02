"""
Generic AuditLog signal registratori.

Har bir kuzatiladigan model uchun `register_audit(Model, org_path)` chaqiriladi
(ro'yxat: `scheduling/apps.py::ready()`). Bu create/update/delete amallarini
avtomatik `AuditLog` jadvaliga yozadi — alohida view kodini o'zgartirish shart
emas.

`org_path` — instance'dan `organizations.Organization`ga boradigan nuqta bilan
ajratilgan yo'l (masalan `"major.organization"`), chunki ko'p modellarda
`organization` maydoni bevosita emas, bog'liq model orqali kelib chiqadi.
"""
from django.db.models.signals import pre_save, post_delete, post_save
from .models import AuditLog
from config.current_user import get_current_user

# Har safar saqlanganda o'zgargandek ko'rinadigan, lekin biznes jihatdan
# ahamiyatsiz "bookkeeping" maydonlar — diff'ga chiqarilmaydi.
_IGNORED_FIELDS = {
    'created_at', 'updated_at', 'uploaded_at', 'generated_at', 'timestamp',
}

# (model_name, pk) -> saqlashdan oldingi maydon qiymatlari
_PRE_SAVE_STATE = {}


def _concrete_field_dict(instance):
    data = {}
    for field in instance._meta.concrete_fields:
        data[field.name] = getattr(instance, field.attname, None)
    return data


def _resolve_organization(instance, org_path):
    if org_path == 'self':
        return instance
    obj = instance
    try:
        for part in org_path.split('.'):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj
    except Exception:
        return None


def register_audit(model, org_path='organization', label=None):
    model_name = label or model.__name__

    def _pre_save(sender, instance, **kwargs):
        if not instance.pk:
            return
        try:
            old = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            return
        _PRE_SAVE_STATE[(model_name, instance.pk)] = _concrete_field_dict(old)

    def _post_save(sender, instance, created, **kwargs):
        org = _resolve_organization(instance, org_path)
        changes = {}
        if not created:
            old = _PRE_SAVE_STATE.pop((model_name, instance.pk), None)
            if old is not None:
                new = _concrete_field_dict(instance)
                for key, new_val in new.items():
                    if key in _IGNORED_FIELDS:
                        continue
                    old_val = old.get(key)
                    if str(old_val) != str(new_val):
                        changes[key] = {'old': str(old_val), 'new': str(new_val)}
                if not changes:
                    # Hech narsa haqiqatan o'zgarmagan (masalan faqat auto_now
                    # maydon yangilangan) — bo'sh UPDATE yozuv yaratmaymiz.
                    return
        AuditLog.objects.create(
            organization=org,
            user=get_current_user(),
            action=AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
            model_name=model_name,
            object_id=instance.pk,
            object_repr=str(instance)[:500],
            changes=changes,
        )

    def _post_delete(sender, instance, **kwargs):
        org = _resolve_organization(instance, org_path)
        AuditLog.objects.create(
            organization=org,
            user=get_current_user(),
            action=AuditLog.Action.DELETE,
            model_name=model_name,
            object_id=instance.pk,
            object_repr=str(instance)[:500],
            changes={},
        )

    pre_save.connect(_pre_save, sender=model, weak=False,
                      dispatch_uid=f'audit-pre-save-{model_name}')
    post_save.connect(_post_save, sender=model, weak=False,
                       dispatch_uid=f'audit-post-save-{model_name}')
    post_delete.connect(_post_delete, sender=model, weak=False,
                         dispatch_uid=f'audit-post-delete-{model_name}')


def connect_all():
    """Kuzatiladigan barcha modellarni ro'yxatdan o'tkazadi."""
    from organizations.models import Organization, Building, Room, Department
    from academic.models import (
        Major, Subject, Curriculum, CurriculumBlock, CurriculumSubject,
        Group, Shift, Para, GroupDayAssignment,
    )
    from accounts.models import User
    from .models import (
        Teacher, TeacherBusyTime, TeacherSubjectAssignment, TeacherMonthlyLoad,
        Schedule, ScheduleEntry, Substitution, LoadSheet, GroupSubject,
    )

    # organizations
    register_audit(Organization, org_path='self', label='Organization')
    register_audit(Building)
    register_audit(Room, org_path='building.organization')
    register_audit(Department)

    # academic
    register_audit(Major)
    register_audit(Subject)
    register_audit(Curriculum, org_path='major.organization')
    register_audit(CurriculumBlock, org_path='curriculum.major.organization')
    register_audit(CurriculumSubject, org_path='block.curriculum.major.organization')
    register_audit(Group)
    register_audit(Shift)
    register_audit(Para, org_path='shift.organization')
    register_audit(GroupDayAssignment, org_path='group.organization')

    # accounts
    register_audit(User)

    # scheduling
    register_audit(Teacher)
    register_audit(TeacherBusyTime, org_path='teacher.organization')
    register_audit(TeacherSubjectAssignment, org_path='teacher.organization')
    register_audit(TeacherMonthlyLoad, org_path='teacher.organization')
    register_audit(Schedule)
    register_audit(ScheduleEntry, org_path='schedule.organization')
    register_audit(Substitution, org_path='schedule_entry.schedule.organization')
    register_audit(LoadSheet, org_path='department.organization')
    register_audit(GroupSubject, org_path='curriculum_subject.block.curriculum.major.organization')
