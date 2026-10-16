"""Construction item equipment configuration."""

from odoo import fields, models


class ConstructionItemEquipment(models.Model):
    """Construction Item Equipment."""

    _name = "construction.item.equipment"
    _description = "Construction Item Equipment"

    item_id = fields.Many2one("construction.item", required=True, ondelete="cascade")
    product_id = fields.Many2one(
        "product.product", required=True, domain=[("is_equipment", "=", True)],
    )
    quantity = fields.Float(default=1.0, string="Quantity")
    cost = fields.Float(related="product_id.standard_price", string="Cost")
