from django.contrib import admin
from .models import Organization, Building, Room


class RoomInline(admin.TabularInline):
    model = Room
    extra = 1


class BuildingInline(admin.TabularInline):
    model = Building
    extra = 1


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [BuildingInline]


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'is_active']
    list_filter = ['organization', 'is_active']
    inlines = [RoomInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'building', 'room_type', 'capacity', 'is_active']
    list_filter = ['room_type', 'is_active']