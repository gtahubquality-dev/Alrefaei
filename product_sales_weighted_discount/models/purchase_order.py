"""Purchase order hooks for product weighted discount updates."""

from odoo import models


class PurchaseOrder(models.Model):
    """Recalculate product discounts when purchase orders are approved."""

    _inherit = 'purchase.order'

    def button_approve(self, force=False):
        """Update product discounts after an RFQ becomes a purchase order."""
        result = getattr(super(), 'button_approve')(force=force)
        self.recalculate_weighted_discounts()
        return result

    def recalculate_weighted_discounts(self):
        """Recalculate weighted discounts for all products on these orders."""
        enabled_orders = self.filtered('free_customizations_enabled')
        enabled_orders.mapped('order_line.product_id').compute_weighted_discount_from_purchase_history()
