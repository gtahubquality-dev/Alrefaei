"""Product variant discount fields and purchase-history calculation."""

from odoo import api, fields, models


class ProductProduct(models.Model):
    """Store sales and weighted purchase discounts on product variants."""

    _inherit = 'product.product'

    weighted_discount = fields.Float(
        string='Weighted Discount (%)',
        digits='Discount',
        help='Average of this product latest two confirmed purchase line discounts.',
    )
    sales_discount = fields.Float(
        string='Sales Discount (%)',
        digits='Discount',
        help='Default sales discount copied to sale order lines.',
    )

    @api.onchange('weighted_discount')
    def onchange_weighted_discount(self):
        """Default sales discount from weighted discount in the product form."""
        if not self.env.company.enable_free_customizations:
            return
        for product in self:
            product.sales_discount = product.weighted_discount - 2

    @api.model_create_multi
    def create(self, vals_list):
        """Default sales discount when products are created with weighted discount."""
        for vals in vals_list:
            if (
                self.env.company.enable_free_customizations
                and 'weighted_discount' in vals
                and 'sales_discount' not in vals
            ):
                vals['sales_discount'] = vals['weighted_discount'] - 2
        return super().create(vals_list)

    def write(self, vals):
        """Default sales discount when weighted discount changes."""
        if (
            self.env.company.enable_free_customizations
            and 'weighted_discount' in vals
            and 'sales_discount' not in vals
        ):
            vals = dict(vals, sales_discount=vals['weighted_discount'] - 2)
        return super().write(vals)

    def compute_weighted_discount_from_purchase_history(self):
        """Update weighted and sales discounts from latest two purchase lines."""
        purchase_order_line_model = self.env['purchase.order.line']
        for product in self:
            purchase_lines = purchase_order_line_model.search([
                ('product_id', '=', product.id),
                ('company_id.enable_free_customizations', '=', True),
                ('order_id.state', 'in', ('purchase', 'done')),
                ('display_type', '=', False),
            ], order='order_id.date_order desc, id desc', limit=2)
            if not purchase_lines:
                continue
            weighted_discount = (
                sum(purchase_lines.mapped('discount')) / len(purchase_lines)
            )
            product.write({
                'weighted_discount': weighted_discount,
                'sales_discount': weighted_discount - 2,
            })
