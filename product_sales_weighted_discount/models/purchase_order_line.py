"""Purchase order line hooks for product weighted discount updates."""

from odoo import api, models


class PurchaseOrderLine(models.Model):
    """Recalculate product discounts when purchase discount history changes."""

    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        """Recalculate discounts for confirmed purchase lines created later."""
        lines = super().create(vals_list)
        confirmed_lines = lines.filtered(
            lambda line: (
                line.free_customizations_enabled
                and line.order_id.state in ('purchase', 'done')
            )
        )
        confirmed_lines.mapped('product_id').compute_weighted_discount_from_purchase_history()
        return lines

    def write(self, vals):
        """Recalculate discounts when product or discount values change."""
        old_products = self.mapped('product_id')
        result = super().write(vals)
        if {'discount', 'product_id', 'order_id'} & set(vals):
            enabled_lines = self.filtered('free_customizations_enabled')
            products = old_products | enabled_lines.mapped('product_id')
            products.compute_weighted_discount_from_purchase_history()
        return result

    def unlink(self):
        """Recalculate discounts when purchase history lines are deleted."""
        products = self.filtered('free_customizations_enabled').mapped('product_id')
        result = super().unlink()
        products.compute_weighted_discount_from_purchase_history()
        return result
