"""Equipment identification on product variants."""

from odoo import fields, models


class ProductProduct(models.Model):
    """ProductProduct."""

    _inherit = "product.product"

    is_equipment = fields.Boolean(string="Is Equipment")
