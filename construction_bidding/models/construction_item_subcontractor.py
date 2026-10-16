"""Construction item subcontractor configuration."""

from odoo import fields, models


class ConstructionItemSubcontractor(models.Model):
    """Construction Item Subcontractor."""

    _name = "construction.item.subcontractor"
    _description = "Construction Item Subcontractor"

    item_id = fields.Many2one("construction.item", required=True, ondelete="cascade")
    product_id = fields.Many2one(
        "product.product", required=True, domain=[("type", "=", "service")],
    )
    quantity = fields.Float(default=1.0, string="Quantity / Hours")
    finished_product_id = fields.Many2one(
        "product.product", string="Finished Product", domain=[("type", "=", "service")],
    )
