"""Construction fleet construction vehicle sheet expense support."""

from odoo import api, fields, models
from odoo.addons.construction_equipment.models.runtime import call_method
from .vehicle_sheet_fields import project_field


class ConstructionVehicleSheetExpense(models.Model):
    """Construction Vehicle Sheet Expense."""

    _name = 'construction.vehicle.sheet.expense'
    _inherit = ['construction.vehicle.sheet.line.mixin']
    _description = 'Vehicle Sheet Other Expense'
    _order = 'sheet_id, date, id'
    date = fields.Date(string='Date', help='Leave empty for the end date of the sheet.')
    expense_kind = fields.Selection(
        [
            ('freight', 'Freight (Nawlon)'),
            ('tips', 'Tips'),
            ('tolls', 'Tolls / Weighbridge'),
            ('loading', 'Loading / Unloading'),
            ('other', 'Other'),
        ],
        string='Expense Type',
        required=True,
        default='freight',
    )
    name = fields.Char(string='Description', required=True)
    amount = fields.Monetary(string='Amount', required=True)
    distribute = fields.Boolean(
        string='Add to Trips Cost',
        default=True,
        help=(
            'Distributed on the trips of the sheet. Otherwise charged '
            'alone to the project where the vehicle was on the expense '
            'date.'
        ),
    )
    project_id = project_field()
    invoice_ref = fields.Char(string='Receipt / Invoice')
    attachment = fields.Binary(string='Receipt Copy', attachment=True)
    attachment_name = fields.Char(string='File Name')

    @api.depends('sheet_id.vehicle_id', 'sheet_id.date_to', 'date', 'distribute')
    def _compute_project_id(self):
        """Expense charged alone: project where the vehicle was on the expense date."""
        for expense in self:
            vehicle = expense.sheet_id.vehicle_id
            when = expense.date or expense.sheet_id.date_to
            if expense.distribute:
                expense.project_id = False
            elif vehicle and when and (not expense.project_id):
                expense.project_id = call_method(
                    vehicle, '_get_project_at', fields.Datetime.to_datetime(when).replace(hour=12)
                )
            else:
                expense.project_id = expense.project_id
