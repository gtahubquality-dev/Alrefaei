"""Custody settlement return for financial custody."""

from odoo import api
from odoo import fields
from odoo import models


class CustodySettlementReturn(models.Model):
    """Custody settlement return."""

    _name = 'custody.settlement.return'
    _description = 'Custody Settlement Returned Item'
    _inherit = ['custody.settlement.lock.mixin']
    _order = 'settlement_id, id'

    def write(self, vals):
        """Write."""
        self._check_settlement_editable()
        return super().write(vals)

    settlement_id = fields.Many2one(
        'custody.settlement', string='Settlement', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='settlement_id.company_id', store=True, string='Company')
    product_id = fields.Many2one(
        'product.product',
        string='Returned Item',
        required=True,
        help="Item returned to the warehouse, e.g. the old brake pads that were replaced.",
    )
    description = fields.Char(string='Description')
    quantity = fields.Float(string='Quantity', digits='Product Unit', default=1.0, required=True)
    uom_id = fields.Many2one('uom.uom', string='Unit')
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Return to Warehouse',
        required=True,
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1
        ),
        domain="[('company_id', '=', company_id)]",
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for item in self:
            if item.product_id:
                item.uom_id = item.product_id.uom_id
