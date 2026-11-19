"""Construction equipment assets account asset support."""

from odoo import fields, models


class AccountAsset(models.Model):
    """Account Asset."""

    _inherit = 'account.asset'
    construction_equipment_ids = fields.One2many(
        'construction.equipment', 'asset_id', string='Construction Equipment'
    )
