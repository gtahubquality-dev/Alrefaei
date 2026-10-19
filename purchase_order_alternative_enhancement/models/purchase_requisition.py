"""Product and historical vendor discounts for purchase agreements."""

from odoo import api, fields, models


class PurchaseRequisition(models.Model):
    _inherit = "purchase.requisition"

    free_customizations_enabled = fields.Boolean(
        related="company_id.enable_free_customizations",
    )

    weighted_discount = fields.Float(
        string="Weighted Discount (%)",
        digits="Discount",
        compute="_compute_discounts",
        inverse="_inverse_weighted_discount",
        help="Common product weighted discount; zero when product discounts differ.",
    )
    vendor_last_discount = fields.Float(
        string="Last Vendor Discount (%)",
        digits="Discount",
        compute="_compute_discounts",
        help="Common last vendor discount across product lines; zero when the values differ.",
    )

    @api.depends("line_ids.weighted_discount", "line_ids.vendor_last_discount", "line_ids.product_id")
    def _compute_discounts(self):
        for requisition in self:
            lines = requisition.line_ids.filtered("product_id")
            weighted_discounts = set(lines.mapped("weighted_discount"))
            vendor_discounts = set(lines.mapped("vendor_last_discount"))
            requisition.weighted_discount = weighted_discounts.pop() if len(weighted_discounts) == 1 else 0.0
            requisition.vendor_last_discount = vendor_discounts.pop() if len(vendor_discounts) == 1 else 0.0

    def _inverse_weighted_discount(self):
        for requisition in self:
            if not requisition.free_customizations_enabled:
                continue
            requisition.line_ids.mapped("product_id").write({
                "weighted_discount": requisition.weighted_discount,
            })


class PurchaseRequisitionLine(models.Model):
    _inherit = "purchase.requisition.line"

    weighted_discount = fields.Float(
        related="product_id.weighted_discount",
        string="Weighted Discount (%)",
        digits="Discount",
        readonly=False,
    )
    vendor_last_discount = fields.Float(
        string="Last Vendor Discount (%)",
        digits="Discount",
        compute="_compute_vendor_last_discount",
    )

    @api.depends("product_id", "requisition_id.vendor_id", "company_id", "company_id.enable_free_customizations")
    def _compute_vendor_last_discount(self):
        for line in self:
            line.vendor_last_discount = 0.0
            if (
                not line.company_id.enable_free_customizations
                or not line.product_id
                or not line.requisition_id.vendor_id
            ):
                continue
            last_line = self.env["purchase.order.line"].search([
                ("product_id", "=", line.product_id.id),
                ("partner_id", "=", line.requisition_id.vendor_id.id),
                ("company_id", "=", line.company_id.id),
                ("display_type", "=", False),
                ("state", "in", ["purchase", "done"]),
            ], order="order_date_approve desc, order_date_order desc, id desc", limit=1)
            line.vendor_last_discount = last_line.discount if last_line else 0.0
