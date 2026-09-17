"""Product variant extensions for product-code based imports."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class ProductProduct(models.Model):
    """Add a custom product code and make variants searchable by it."""

    _inherit = 'product.product'

    product_code = fields.Char(
        string='Product Code',
        copy=False,
        index=True,
        help='Code used to match products when importing RFQ lines.',
    )

    @api.constrains('product_code')
    def check_unique_product_code(self):
        """Prevent assigning the same product code to multiple variants."""
        if not self.env.company.enable_free_customizations:
            return
        for product in self.filtered('product_code'):
            duplicate = self.search([
                ('product_code', '=', product.product_code),
                ('id', '!=', product.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    self.env._("Product Code '%s' is already used by another product.")
                    % product.product_code
                )

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """Search exact product-code matches before falling back to Odoo search."""
        if (
            self.env.company.enable_free_customizations
            and name
            and operator in ('=', 'ilike', '=ilike', 'like', '=like')
        ):
            products = self.search(
                Domain(domain or Domain.TRUE) & Domain('product_code', '=', name),
                limit=limit,
            )
            if products:
                return [(product.id, product.display_name) for product in products.sudo()]
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)
