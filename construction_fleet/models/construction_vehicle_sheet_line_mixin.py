"""Construction fleet construction vehicle sheet line mixin support."""

from odoo import _, api, models, fields
from odoo.exceptions import UserError
from odoo.addons.construction_equipment.models.runtime import call_method


class ConstructionVehicleSheetLineMixin(models.AbstractModel):
    """Trips and expenses of a vehicle sheet are frozen once the sheet is submitted to
    the custody settlement (reopened by Reset to Draft)."""

    _name = 'construction.vehicle.sheet.line.mixin'
    _description = 'Vehicle Sheet Lines Lock'
    sheet_id = fields.Many2one(
        'construction.vehicle.sheet', string='Sheet', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='sheet_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='sheet_id.currency_id', string='Currency')

    def _check_sheet_draft(self):
        if not self.env.su and any(
            (state not in ('draft', False) for state in self.sheet_id.mapped('state'))
        ):
            raise UserError(_('Trips and expenses can only be changed on draft vehicle sheets.'))

    @api.model_create_multi
    def create(self, vals_list):
        """Create records using the existing defaults and sequence values."""
        records = super().create(vals_list)
        call_method(records, '_check_sheet_draft')
        return records

    def write(self, vals):
        """Update records while preserving the existing workflow checks."""
        self._check_sheet_draft()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_submitted_sheet(self):
        self._check_sheet_draft()
