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
