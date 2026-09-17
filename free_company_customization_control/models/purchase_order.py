"""Company helper fields for purchase order views and logic."""

from odoo import fields, models


class PurchaseOrder(models.Model):
    """Expose the order company's customization flag to purchase orders."""

    _inherit = "purchase.order"

    free_customizations_enabled = fields.Boolean(
        related="company_id.enable_free_customizations",
    )
