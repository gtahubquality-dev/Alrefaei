"""Company helper fields for purchase order line views and logic."""

from odoo import fields, models


class PurchaseOrderLine(models.Model):
    """Expose the line company's customization flag to purchase order lines."""

    _inherit = "purchase.order.line"

    free_customizations_enabled = fields.Boolean(
        related="company_id.enable_free_customizations",
    )
