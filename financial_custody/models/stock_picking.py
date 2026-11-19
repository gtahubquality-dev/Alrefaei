"""Stock picking for financial custody."""

from odoo import fields
from odoo import models


class StockPicking(models.Model):
    """Stock picking."""

    _inherit = 'stock.picking'

    custody_settlement_id = fields.Many2one(
        'custody.settlement',
        string='Custody Settlement',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )
