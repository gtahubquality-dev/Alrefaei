"""Construction fleet hr employee public support."""

from odoo import fields, models


class HrEmployeePublic(models.Model):
    """Hr Employee Public."""

    _inherit = 'hr.employee.public'
    construction_driver_ids = fields.One2many(
        'construction.driver', 'employee_id', string='Driver Profiles'
    )
