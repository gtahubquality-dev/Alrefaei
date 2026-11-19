"""Construction fleet construction vehicle support."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ConstructionEquipment(models.Model):
    """Construction Equipment."""

    _inherit = 'construction.equipment'
    driver_id = fields.Many2one(
        'construction.driver', string='Assigned Driver', tracking=True, index=True
    )

    @api.constrains('category', 'license_plate', 'driver_id', 'active')
    def _check_vehicle_data(self):
        res = super()._check_vehicle_data()
        for equipment in self.filtered(lambda e: e.is_vehicle and e.active):
            if not equipment.driver_id:
                raise ValidationError(_('A driver must be assigned to vehicle %s.', equipment.name))
        return res
