"""Company helper fields for sale order line views and logic."""

from odoo import fields, models


class SaleOrderLine(models.Model):
    """Expose the line company's customization flag to sale order lines."""

    _inherit = "sale.order.line"

    free_customizations_enabled = fields.Boolean(
        related="company_id.enable_free_customizations",
    )
