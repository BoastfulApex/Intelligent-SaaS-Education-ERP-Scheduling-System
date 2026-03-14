from rest_framework import serializers
from .models import Organization, Building, Room, Department


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class BuildingSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Building
        fields = ['id', 'organization', 'organization_name',
                  'name', 'address', 'is_active']
        read_only_fields = ['id', 'organization']
        
       

class RoomSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source='building.name', read_only=True)

    class Meta:
        model = Room
        fields = ['id', 'building', 'building_name', 'name', 'room_type', 'capacity', 'is_active']
        read_only_fields = ['id']
        

class DepartmentSerializer(serializers.ModelSerializer):
    manager_name = serializers.CharField(
        source='manager.get_full_name', read_only=True
    )

    class Meta:
        model = Department
        fields = ['id', 'organization', 'name', 'order',
                  'manager', 'manager_name', 'is_active']
        read_only_fields = ['id', 'organization']