"""Construction fleet custody settlement support."""

from odoo import _, fields, models


class CustodySettlement(models.Model):
    """Custody Settlement."""

    _inherit = 'custody.settlement'
    vehicle_sheet_id = fields.Many2one(
        'construction.vehicle.sheet',
        string='Vehicle Custody Sheet',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )

    def action_post(self):
        """Action post."""
        res = super().action_post()
        sheets = self.sudo().vehicle_sheet_id.filtered(lambda s: s.state == 'submitted')
        sheets.write({'state': 'done'})
        return res

    def action_cancel(self):
        """Action cancel."""
        res = super().action_cancel()
        for sheet in self.sudo().vehicle_sheet_id.filtered(lambda s: s.state == 'submitted'):
            sheet.write({'state': 'draft', 'settlement_id': False})
            sheet.message_post(
                body=_('The custody settlement was cancelled; the sheet is back to draft.')
            )
        return res
