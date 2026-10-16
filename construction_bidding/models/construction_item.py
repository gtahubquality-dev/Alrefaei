"""Independent construction item configuration."""

from odoo import fields, models


class ConstructionItem(models.Model):
    """Construction Item."""

    _name = "construction.item"
    _description = "Construction Item"

    name = fields.Char(string="Item Name", required=True)
    product_id = fields.Many2one(
        "product.product", string="Finished Product", required=True,
        domain=[("type", "=", "service")],
    )
    quantity = fields.Float(default=1.0, required=True)
    material_line_ids = fields.One2many("construction.item.material", "item_id", copy=True)
    subcontractor_line_ids = fields.One2many(
        "construction.item.subcontractor", "item_id", copy=True,
    )
    equipment_line_ids = fields.One2many("construction.item.equipment", "item_id", copy=True)
