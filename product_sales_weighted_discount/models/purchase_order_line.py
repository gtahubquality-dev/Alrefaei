"""Purchase order line hooks for product weighted discount updates."""

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    """Recalculate product discounts when purchase discount history changes."""

    _inherit = 'purchase.order.line'

    weighted_discount = fields.Float(
        string='Weighted Discount (%)',
        compute='_compute_weighted_discount',
        store=True,
        precompute=True,
        digits='Discount',
        readonly=False,
    )

    @api.depends('product_id')
    def _compute_weighted_discount(self):
        """Keep a line's discount stable when product purchase history changes."""
        for line in self:
            line.weighted_discount = line.product_id.weighted_discount

    @api.depends('weighted_discount', 'free_customizations_enabled')
    def _compute_amount(self):
        """Recompute standard amounts when the custom discount changes."""
        return super()._compute_amount()

    def _prepare_base_line_for_taxes_computation(self):
        """Apply the weighted discount before Odoo's standard discount and taxes."""
        base_line = super()._prepare_base_line_for_taxes_computation()
        if self.free_customizations_enabled and not self.display_type:
            base_line['price_unit'] *= 1 - self.weighted_discount / 100
        return base_line

    @api.depends('weighted_discount', 'free_customizations_enabled')
    def _compute_price_unit_discounted(self):
        """Keep stock valuation consistent with the purchase amount."""
        super()._compute_price_unit_discounted()
        for line in self:
            if line.free_customizations_enabled and not line.display_type:
                line.price_unit_discounted *= 1 - line.weighted_discount / 100

    def _prepare_account_move_line(self, move=False):
        """Carry the weighted discount into the bill's unit price."""
        vals = super()._prepare_account_move_line(move=move)
        if self.free_customizations_enabled and not self.display_type:
            vals['price_unit'] *= 1 - self.weighted_discount / 100
        return vals

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
