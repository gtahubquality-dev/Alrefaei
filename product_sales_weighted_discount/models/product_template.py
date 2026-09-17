"""Product template discount fields exposed for single-variant products."""

from odoo import api, fields, models


class ProductTemplate(models.Model):
    """Expose variant discount fields on product templates."""

    _inherit = 'product.template'

    weighted_discount = fields.Float(
        string='Weighted Discount (%)',
        compute='compute_weighted_discount',
        inverse='set_weighted_discount',
        digits='Discount',
        store=True,
    )
    sales_discount = fields.Float(
        string='Sales Discount (%)',
        compute='compute_sales_discount',
        inverse='set_sales_discount',
        digits='Discount',
        store=True,
    )

    @api.onchange('weighted_discount')
    def onchange_weighted_discount(self):
        """Default sales discount from weighted discount in the template form."""
        if not self.env.company.enable_free_customizations:
            return
        for template in self:
            template.sales_discount = template.weighted_discount - 2

    @api.depends('product_variant_ids.weighted_discount')
    def compute_weighted_discount(self):
        """Read weighted discount from the single product variant."""
        for template in self:
            variants = template['product_variant_ids']
            template['weighted_discount'] = (
                variants['weighted_discount'] if len(variants) == 1 else 0.0
            )

    def set_weighted_discount(self):
        """Write weighted discount onto the single product variant."""
        for template in self:
            variants = template['product_variant_ids']
            if len(variants) == 1:
                variants['weighted_discount'] = template['weighted_discount']

    @api.depends('product_variant_ids.sales_discount')
    def compute_sales_discount(self):
        """Read sales discount from the single product variant."""
        for template in self:
            variants = template['product_variant_ids']
            template['sales_discount'] = (
                variants['sales_discount'] if len(variants) == 1 else 0.0
            )

    def set_sales_discount(self):
        """Write sales discount onto the single product variant."""
        for template in self:
            variants = template['product_variant_ids']
            if len(variants) == 1:
                variants['sales_discount'] = template['sales_discount']
