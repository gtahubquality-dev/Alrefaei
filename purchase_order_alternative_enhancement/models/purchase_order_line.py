"""Purchase order line fields for alternative comparison enhancements."""

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    """Extend purchase order lines with comparison-only values."""

    _inherit = "purchase.order.line"

    weighted_discount = fields.Float(
        related="product_id.weighted_discount",
        string="Weighted Discount (%)",
        digits="Discount",
        readonly=True,
    )
    reorder_min_qty = fields.Float(
        string="Min Quantity",
        compute="_compute_reorder_stock_fields",
        digits="Product Unit",
    )
    is_below_reorder_min = fields.Boolean(
        compute="_compute_reorder_stock_fields",
    )
    vendor_last_discount = fields.Float(
        string="Last Vendor Discount (%)",
        compute="_compute_vendor_last_discount",
        digits="Discount",
    )
    order_date_approve = fields.Datetime(
        related="order_id.date_approve",
        store=True,
    )
    order_date_order = fields.Datetime(
        related="order_id.date_order",
        store=True,
    )

    def get_reorder_min_quantity(self):
        """Return the highest reorder minimum configured for the line product."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            return 0.0
        orderpoints = self.env["stock.warehouse.orderpoint"].sudo().search([
            ("product_id", "=", self.product_id.id),
            ("company_id", "=", self.company_id.id),
        ])
        return max(orderpoints.mapped("product_min_qty") or [0.0])

    def get_previous_vendor_purchase_line(self):
        """Return the latest historical purchase line for the same vendor/product."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            return self.env["purchase.order.line"]
        excluded_orders = self.order_id | self.order_id.alternative_po_ids
        return self.env["purchase.order.line"].sudo().search([
            ("id", "!=", self.id),
            ("order_id", "not in", excluded_orders.ids),
            ("product_id", "=", self.product_id.id),
            ("partner_id", "=", self.partner_id.id),
            ("company_id", "=", self.company_id.id),
            ("display_type", "=", False),
            ("state", "in", ["purchase", "done"]),
        ], order="order_date_approve desc, order_date_order desc, id desc", limit=1)

    @api.depends("product_id", "company_id")
    def _compute_reorder_stock_fields(self):
        for line in self:
            if not line.free_customizations_enabled or not line.product_id:
                line.reorder_min_qty = 0.0
                line.is_below_reorder_min = False
                continue

            min_qty = line.get_reorder_min_quantity()
            qty_available = line.product_id.with_context(
                company_id=line.company_id.id
            ).qty_available

            line.reorder_min_qty = min_qty
            line.is_below_reorder_min = min_qty > 0 and qty_available <= min_qty

    @api.depends("product_id", "partner_id", "company_id", "order_id.alternative_po_ids")
    def _compute_vendor_last_discount(self):
        for line in self:
            if not line.free_customizations_enabled or not line.product_id or not line.partner_id:
                line.vendor_last_discount = 0.0
                continue

            last_line = line.get_previous_vendor_purchase_line()
            line.vendor_last_discount = last_line.discount if last_line else 0.0
