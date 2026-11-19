"""Construction equipment construction equipment dashboard support."""

from odoo.addons.construction_management.models.construction_equipment import (
    EQUIPMENT_CATEGORIES,
    VEHICLE_CATEGORIES,
)

MACHINE_CATEGORIES = [
    (key, label) for (key, label) in EQUIPMENT_CATEGORIES if key not in VEHICLE_CATEGORIES
]
COST_GROUPS = [
    ('usage', 'Operation (hours)', 'bg-primary'),
    ('fuel', 'Fuel & Oil', 'bg-info'),
    ('maintenance', 'Maintenance & Repair', 'bg-warning'),
    ('rental', 'Rental', 'bg-danger'),
    ('other', 'Transport & Other', 'bg-secondary'),
]
EXPENSE_GROUP = {
    'fuel': 'fuel',
    'oil': 'fuel',
    'maintenance': 'maintenance',
    'repair': 'maintenance',
    'rental': 'rental',
    'transport': 'other',
    'other': 'other',
}
RENTAL_ALERT_DAYS = 7
