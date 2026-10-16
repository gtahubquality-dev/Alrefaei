"""Construction item material configuration."""

from odoo import fields, models


class ConstructionItemMaterial(models.Model):
    """Construction Item Material."""

    _name = "construction.item.material"
    _description = "Construction Item Material"

    item_id = fields.Many2one("construction.item", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(default=1.0, string="Quantity")
    cost = fields.Float(related="product_id.standard_price", string="Cost")
