"""Construction fleet res company support."""

from odoo import fields, models


class ResCompany(models.Model):
    """Res Company."""

    _inherit = 'res.company'
    construction_transport_expense_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', "
            "'liability_payable')), ('active', '=', True)]"
        ),
        string='Vehicle Transport Cost Account',
        help='Expense account charged with the trips settled through the driver custody sheets.',
    )
