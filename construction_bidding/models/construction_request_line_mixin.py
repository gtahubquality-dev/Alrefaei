"""Shared fields for material and equipment request lines."""

from odoo import fields, models


class ConstructionRequestLineMixin(models.AbstractModel):
    """Common BOQ source, product, description, quantity, and unit fields."""

    _name = "construction.request.line.mixin"
    _description = "Construction Request Line Mixin"

    boq_line_id = fields.Many2one("construction.boq.line", ondelete="set null")
    product_id = fields.Many2one("product.product")
    description = fields.Text()
    quantity = fields.Float(string="Planned Quantity")
    uom_id = fields.Many2one("uom.uom", string="UoM")
