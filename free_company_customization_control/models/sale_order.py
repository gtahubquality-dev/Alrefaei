"""Company helper fields for sale order views and logic."""

from odoo import fields, models


class SaleOrder(models.Model):
    """Expose the order company's customization flag to sale orders."""

    _inherit = "sale.order"

    free_customizations_enabled = fields.Boolean(
        related="company_id.enable_free_customizations",
    )
