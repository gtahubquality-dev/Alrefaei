"""Custody settlement line for financial custody."""

from odoo import _
from odoo import fields
from odoo import models
from odoo.exceptions import UserError


class CustodySettlementLine(models.Model):
    """Custody settlement line."""

    _name = 'custody.settlement.line'
    _description = 'Custody Settlement Expense'
    _inherit = ['analytic.mixin', 'custody.settlement.lock.mixin']
    _order = 'settlement_id, sequence, id'

    settlement_id = fields.Many2one(
        'custody.settlement', string='Settlement', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='settlement_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='settlement_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    date = fields.Date(string='Expense Date', default=fields.Date.context_today)
    name = fields.Char(string='Description', required=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    invoice_ref = fields.Char(string='Invoice Number')
    invoice_date = fields.Date(string='Invoice Date')
    attachment = fields.Binary(string='Invoice Copy', attachment=True)
    attachment_name = fields.Char(string='Invoice File Name')
    account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    amount = fields.Monetary(string='Amount', required=True)

    def _get_account(self):
        self.ensure_one()
        account = self.account_id or self.company_id.expense_account_id
        if not account:
            raise UserError(_('Please set the expense account of "%s".', self.name))
        return account

    def write(self, vals):
        """Write."""
        if (
            self.filtered(lambda l: l.settlement_id.state not in ('draft', False))
            and {'amount', 'account_id', 'analytic_distribution', 'name'}.intersection(vals)
            and not self.env.user.has_group('financial_custody.group_custody_manager')
        ):
            raise UserError(
                _('Lines of a submitted settlement can only be modified by the custody manager.')
            )
        if self.filtered(lambda l: l.settlement_id.state == 'posted') and {
            'amount',
            'account_id',
            'analytic_distribution',
        }.intersection(vals):
            raise UserError(_('Lines of a posted settlement cannot be modified.'))
        return super().write(vals)
