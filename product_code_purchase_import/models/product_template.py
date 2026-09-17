"""Product template extensions for product-code based imports."""

from odoo import api, fields, models


class ProductTemplate(models.Model):
    """Expose product code on templates when there is a single variant."""

    _inherit = 'product.template'

    product_code = fields.Char(
        string='Product Code',
        compute='compute_product_code',
        inverse='set_product_code',
        store=True,
    )

    @api.depends('product_variant_ids.product_code')
    def compute_product_code(self):
        """Read the product code from the single product variant."""
        for template in self:
            variants = template['product_variant_ids']
            template['product_code'] = variants['product_code'] if len(variants) == 1 else False

    def set_product_code(self):
        """Write the template product code onto the single product variant."""
        for template in self:
            variants = template['product_variant_ids']
            if len(variants) == 1:
                variants['product_code'] = template['product_code']
