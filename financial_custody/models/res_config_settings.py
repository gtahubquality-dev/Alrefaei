"""Res config settings for financial custody."""

from odoo import fields
from odoo import models


class ResConfigSettings(models.TransientModel):
    """Res config settings."""

    _inherit = 'res.config.settings'

    custody_account_id = fields.Many2one(related='company_id.custody_account_id', readonly=False)
    custody_journal_id = fields.Many2one(
        related='company_id.custody_journal_id',
        readonly=False,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    custody_settlement_journal_id = fields.Many2one(
        related='company_id.custody_settlement_journal_id',
        readonly=False,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
    )
    custody_settlement_threshold = fields.Float(
        related='company_id.custody_settlement_threshold', readonly=False
    )
