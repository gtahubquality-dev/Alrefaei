"""Sale order line sales discount defaults."""

from odoo import api, fields, models


class SaleOrderLine(models.Model):
    """Copy the product sales discount onto sale order lines."""

    _inherit = 'sale.order.line'

    sales_discount = fields.Float(
        string='Sales Discount (%)',
        digits='Discount',
        help='Copied from the product sales discount and editable per sale order line.',
    )

    @api.depends('sales_discount', 'free_customizations_enabled')
    def _compute_amount(self):
        """Recompute standard amounts when the custom discount changes."""
        return super()._compute_amount()

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        """Apply the sales discount before Odoo's standard discount and taxes."""
        base_line = super()._prepare_base_line_for_taxes_computation(**kwargs)
        if self.free_customizations_enabled and not self.display_type:
            base_line['price_unit'] *= 1 - self.sales_discount / 100
        return base_line

    def _prepare_invoice_line(self, **optional_values):
        """Carry the sales discount into the invoice's unit price."""
        vals = super()._prepare_invoice_line(**optional_values)
        if (
            self.free_customizations_enabled
            and not self.display_type
            and 'price_unit' in vals
        ):
            vals['price_unit'] *= 1 - self.sales_discount / 100
        return vals

    @api.onchange('product_id')
    def onchange_product_id_sales_discount(self):
        """Copy product sales discount when changing the line product."""
        for line in self:
            if line.free_customizations_enabled:
                line.sales_discount = line.product_id.sales_discount

    @api.model_create_multi
    def create(self, vals_list):
        """Copy product sales discount when sale lines are created."""
        for vals in vals_list:
            enabled = self.env.company.enable_free_customizations
            if vals.get('order_id'):
                order = self.env['sale.order'].browse(vals['order_id'])
                enabled = order.company_id.enable_free_customizations
            if enabled and vals.get('product_id') and 'sales_discount' not in vals:
                product = self.env['product.product'].browse(vals['product_id'])
                vals['sales_discount'] = product.sales_discount
        return super().create(vals_list)
