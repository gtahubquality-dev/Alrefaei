"""Construction fleet res config settings support."""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Res Config Settings."""

    _inherit = 'res.config.settings'
    construction_transport_expense_account_id = fields.Many2one(
        related='company_id.construction_transport_expense_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', "
            "'liability_payable')), ('active', '=', True)]"
        ),
    )
