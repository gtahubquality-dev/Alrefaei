"""Purchase order line extensions for importing by product code."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PurchaseOrderLine(models.Model):
    """Resolve imported RFQ line product codes to products."""

    _inherit = 'purchase.order.line'

    product_code = fields.Char(
        string='Product Code',
        copy=False,
        help='Enter or import this code to automatically select the matching product.',
    )

    @api.model
    def is_product_code_import_enabled(self, vals=None):
        """Return whether product-code import behavior is active for the line company."""
        company = self.company_id or self.env.company
        vals = vals or {}
        if vals.get('order_id'):
            order = self.env['purchase.order'].browse(vals['order_id'])
            company = order.company_id or company
        elif vals.get('company_id'):
            company = self.env['res.company'].browse(vals['company_id'])
        return bool(company.enable_free_customizations)

    @api.model
    def get_product_by_product_code(self, product_code):
        """Return one purchasable product matching the given product code."""
        code = (product_code or '').strip()
        if not code:
            return self.env['product.product']

        products = self.env['product.product'].search([
            ('product_code', '=', code),
            ('purchase_ok', '=', True),
        ], limit=2)
        if not products:
            raise ValidationError(
                self.env._("No purchasable product found with Product Code '%s'.") % code
            )
        if len(products) > 1:
            raise ValidationError(
                self.env._("More than one purchasable product has Product Code '%s'.") % code
            )
        return products

    @api.model
    def apply_product_code_to_vals(self, vals):
        """Set product_id from product_code in create/write values."""
        if not self.is_product_code_import_enabled(vals):
            return vals
        if vals.get('product_code'):
            vals['product_code'] = vals['product_code'].strip()
            product = self.get_product_by_product_code(vals['product_code'])
            if vals.get('product_id') and vals['product_id'] != product.id:
                raise ValidationError(
                    self.env._("Product Code '%(code)s' does not match the selected product.")
                    % {'code': vals['product_code']}
                )
            vals['product_id'] = product.id
        elif vals.get('product_id'):
            vals['product_code'] = (
                self.env['product.product'].browse(vals['product_id']).product_code
            )
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        """Resolve product codes before creating imported order lines."""
        for vals in vals_list:
            self.apply_product_code_to_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        """Resolve product codes before updating order lines."""
        if 'product_code' in vals or 'product_id' in vals:
            vals = dict(vals)
            self.apply_product_code_to_vals(vals)
        return super().write(vals)

    @api.onchange('product_code')
    def onchange_product_code(self):
        """Select the matching product when a product code is entered."""
        for line in self:
            if line.is_product_code_import_enabled() and line.product_code:
                line.product_id = line.get_product_by_product_code(line.product_code)

    @api.onchange('product_id')
    def onchange_product_id_product_code(self):
        """Copy the selected product code onto the purchase line."""
        for line in self:
            if line.is_product_code_import_enabled():
                line.product_code = line.product_id.product_code
