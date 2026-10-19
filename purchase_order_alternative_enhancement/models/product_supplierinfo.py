"""Product and historical vendor discounts on vendor pricelists."""

from odoo import api, fields, models


class ProductSupplierinfo(models.Model):
    _inherit = "product.supplierinfo"

    free_customizations_enabled = fields.Boolean(
        compute="_compute_free_customizations_enabled",
    )
    weighted_discount = fields.Float(
        string="Weighted Discount (%)",
        compute="_compute_weighted_discount",
        digits="Discount",
    )
    vendor_last_discount = fields.Float(
        string="Last Vendor Discount (%)",
        compute="_compute_vendor_last_discount",
        digits="Discount",
    )

    @api.depends("company_id.enable_free_customizations")
    @api.depends_context("company")
    def _compute_free_customizations_enabled(self):
        for supplier in self:
            company = supplier.company_id or self.env.company
            supplier.free_customizations_enabled = company.enable_free_customizations

    @api.depends("product_id.weighted_discount", "product_tmpl_id.weighted_discount")
    def _compute_weighted_discount(self):
        for supplier in self:
            product = supplier.product_id or supplier.product_tmpl_id
            supplier.weighted_discount = product.weighted_discount if product else 0.0

    @api.depends("product_id", "product_tmpl_id", "partner_id", "company_id", "free_customizations_enabled")
    @api.depends_context("company")
    def _compute_vendor_last_discount(self):
        for supplier in self:
            supplier.vendor_last_discount = 0.0
            if not supplier.free_customizations_enabled or not supplier.partner_id:
                continue
            if not supplier.product_id and not supplier.product_tmpl_id:
                continue

            company = supplier.company_id or self.env.company
            domain = [
                ("partner_id", "=", supplier.partner_id.id),
                ("company_id", "=", company.id),
                ("display_type", "=", False),
                ("state", "in", ["purchase", "done"]),
            ]
            if supplier.product_id:
                domain.append(("product_id", "=", supplier.product_id.id))
            else:
                domain.append(("product_id.product_tmpl_id", "=", supplier.product_tmpl_id.id))
            last_line = self.env["purchase.order.line"].search(
                domain,
                order="order_date_approve desc, order_date_order desc, id desc",
                limit=1,
            )
            supplier.vendor_last_discount = last_line.discount if last_line else 0.0
