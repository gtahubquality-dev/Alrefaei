"""Purchase order helpers for alternative comparison highlighting."""

from collections import defaultdict

from odoo import models


class PurchaseOrder(models.Model):
    """Extend purchase orders with extra comparison helper methods."""

    _inherit = "purchase.order"

    def get_tender_best_weighted_discount_lines(self):
        """Return alternative line ids with the highest weighted discount per product."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            return []
        purchase_order_line = self.env["purchase.order.line"]
        product_to_best_weighted_discount_line = defaultdict(lambda: purchase_order_line)
        po_alternatives = self | self.alternative_po_ids

        for line in po_alternatives.order_line:
            if (
                not line.product_qty
                or not line.price_total_cc
                or line.state in ["cancel", "purchase"]
            ):
                continue

            best_lines = product_to_best_weighted_discount_line[line.product_id]
            if not best_lines:
                product_to_best_weighted_discount_line[line.product_id] = line
            elif best_lines[0].weighted_discount < line.weighted_discount:
                product_to_best_weighted_discount_line[line.product_id] = line
            elif best_lines[0].weighted_discount == line.weighted_discount:
                product_to_best_weighted_discount_line[line.product_id] |= line

        best_weighted_discount_ids = set()
        for lines in product_to_best_weighted_discount_line.values():
            best_weighted_discount_ids.update(lines.ids)

        return list(best_weighted_discount_ids)

    def get_tender_low_stock_lines(self):
        """Return alternative line ids whose product is at or below reorder minimum."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            return []
        po_alternatives = self | self.alternative_po_ids
        low_stock_lines = self.env["purchase.order.line"]

        for line in po_alternatives.order_line:
            if not line.product_qty or line.state in ["cancel", "purchase"]:
                continue
            if line.is_below_reorder_min:
                low_stock_lines |= line

        return low_stock_lines.ids
