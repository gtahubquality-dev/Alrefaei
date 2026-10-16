"""Shared product fields and actions for project and BOQ deductions."""

from odoo import api, fields, models

from .boq_common import form_action


class ConstructionDeductionMixin(models.AbstractModel):
    """Product, unit, price, and product navigation shared by deductions."""

    _name = "construction.deduction.mixin"
    _description = "Construction Deduction Mixin"

    product_id = fields.Many2one("product.product", string="Product", required=True)
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="UoM",
        required=True,
    )
    price_unit = fields.Float(string="Price")

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.product_uom_id = line.product_id.uom_id
                line.price_unit = line.product_id.lst_price

    def action_open_product(self):
        """Open the deduction product."""
        self.ensure_one()
        return form_action("Product", "product.product", self.product_id.id)
