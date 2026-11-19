"""Res company for financial custody."""

from odoo import fields, models


class ResCompany(models.Model):
    """Res company."""

    _inherit = 'res.company'

    custody_account_id = fields.Many2one(
        'account.account',
        string='Custody Account',
        help=(
            "Account holding the cash advanced to employees until it is settled (employee custody"
            " receivable)."
        ),
    )
    custody_journal_id = fields.Many2one(
        'account.journal',
        string='Default Disbursement Journal',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', id)]",
    )
    custody_settlement_journal_id = fields.Many2one(
        'account.journal',
        string='Custody Settlement Journal',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
    )
    custody_settlement_threshold = fields.Float(
        string='Minimum Settlement Before New Custody (%)',
        default=50.0,
        help=(
            "An employee cannot request a new custody while the previous one is settled below this"
            " percentage."
        ),
    )
