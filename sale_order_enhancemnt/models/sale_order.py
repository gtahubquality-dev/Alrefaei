"""Sale order customer, inventory, and quick-add enhancements."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    """Extend sale orders with credit, stock visibility, and quick line add."""

    _inherit = "sale.order"

    company_currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Company Currency",
        readonly=True,
    )
    partner_phone = fields.Char(
        related="partner_id.phone",
        string="Phone",
        readonly=True,
    )
    partner_credit_limit = fields.Float(
        related="partner_id.credit_limit",
        string="Partner Limit",
        readonly=True,
    )
    partner_total_receivable = fields.Monetary(
        related="partner_id.credit",
        string="Total Receivable",
        currency_field="company_currency_id",
        readonly=True,
    )
    inventory_product_id = fields.Many2one(
        "product.product",
        string="Product",
        domain=[("sale_ok", "=", True)],
    )
    inventory_product_qty = fields.Float(
        string="Quantity",
        default=1.0,
        digits="Product Unit",
    )
    inventory_location_ids = fields.Many2many(
        "stock.location",
        "sale_order_inventory_location_rel",
        "order_id",
        "location_id",
        string="Inventory Locations",
        compute="_compute_inventory_stock",
    )
    positive_inventory_location_ids = fields.Many2many(
        "stock.location",
        "sale_order_positive_inventory_location_rel",
        "order_id",
        "location_id",
        string="Available Locations",
        compute="_compute_inventory_stock",
    )
    inventory_location_id = fields.Many2one(
        "stock.location",
        string="Location",
        domain=(
            "[('usage', '=', 'internal'), '|', "
            "('company_id', '=', False), ('company_id', '=', company_id)]"
        ),
    )
    inventory_total_onhand_qty = fields.Float(
        string="Total On Hand",
        compute="_compute_inventory_stock",
        digits="Product Unit",
    )
    location_onhand_qty = fields.Float(
        string="Location On Hand",
        compute="_compute_location_onhand_qty",
        digits="Product Unit",
    )
    inventory_location_button_data = fields.Json(
        compute="_compute_inventory_stock",
    )

    def _get_inventory_quant_domain(self, product):
        """Keep stock figures within the order company and internal locations."""
        self.ensure_one()
        return [
            ("product_id", "=", product.id),
            ("company_id", "=", self.company_id.id),
            ("location_id.usage", "=", "internal"),
        ]

    def get_location_onhand_quantity(self, product, location):
        """Return physical stock at one location, including reserved units."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            return 0.0
        quants = self.env["stock.quant"].sudo().search(
            self._get_inventory_quant_domain(product) + [("location_id", "=", location.id)]
        )
        return sum(quants.mapped("quantity"))

    @api.depends("inventory_product_id", "company_id", "free_customizations_enabled")
    def _compute_inventory_stock(self):
        """Refresh all-location stock and button payload together on product onchange."""
        for order in self:
            order.inventory_total_onhand_qty = 0.0
            order.inventory_location_ids = False
            order.positive_inventory_location_ids = False
            order.inventory_location_button_data = []
            if not order.free_customizations_enabled or not order.inventory_product_id:
                continue

            product = order.inventory_product_id.with_company(order.company_id)
            quantities = self.env["stock.quant"].sudo()._read_group(
                order._get_inventory_quant_domain(product),
                ["location_id"],
                ["quantity:sum"],
            )
            order.inventory_total_onhand_qty = sum(quantity for _location, quantity in quantities)
            location_ids = []
            buttons = []
            for location, quantity in quantities:
                if quantity <= 0:
                    continue
                location_ids.append(location.id)
                buttons.append({
                    "location_id": location.id,
                    "location_name": location.display_name,
                    "product_id": product.id,
                    "company_id": order.company_id.id,
                    "quantity": quantity,
                })
            order.inventory_location_ids = location_ids
            order.positive_inventory_location_ids = location_ids
            order.inventory_location_button_data = buttons

    @api.depends("inventory_product_id", "inventory_location_id", "inventory_total_onhand_qty", "company_id", "free_customizations_enabled")
    def _compute_location_onhand_qty(self):
        for order in self:
            if not order.free_customizations_enabled or not order.inventory_product_id:
                order.location_onhand_qty = 0.0
                continue

            product = order.inventory_product_id.with_company(order.company_id)
            if order.inventory_location_id:
                order.location_onhand_qty = order.get_location_onhand_quantity(
                    product,
                    order.inventory_location_id,
                )
            else:
                order.location_onhand_qty = order.inventory_total_onhand_qty

    @api.onchange("inventory_product_id", "warehouse_id", "company_id")
    def _onchange_warehouse_id_clear_inventory_location(self):
        """Clear stale location choices when the stock selection changes."""
        for order in self:
            order.inventory_location_id = False

    def action_view_inventory_total_onhand(self):
        """Open physical stock for the selected product in all internal locations."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            raise UserError(self.env._("This customization is not enabled for this company."))
        if not self.inventory_product_id:
            raise UserError(self.env._("Please choose a product first."))
        action = self.env.ref("stock.stock_quant_action").sudo().read()[0]
        product_id = getattr(self.inventory_product_id, "id", False)
        action["domain"] = self._get_inventory_quant_domain(self.inventory_product_id) + [
            ("quantity", "!=", 0),
        ]
        action["context"] = {
            "search_default_internal_loc": 1,
            "default_product_id": product_id,
        }
        return action

    def action_view_inventory_location_onhand(self):
        """Open positive stock quants for the selected product and location."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            raise UserError(self.env._("This customization is not enabled for this company."))
        if not self.inventory_product_id:
            raise UserError(self.env._("Please choose a product first."))
        if not self.inventory_location_id:
            raise UserError(self.env._("Please choose a location first."))
        action = self.env.ref("stock.stock_quant_action").sudo().read()[0]
        product_id = getattr(self.inventory_product_id, "id", False)
        location_id = getattr(self.inventory_location_id, "id", False)
        action["domain"] = self._get_inventory_quant_domain(self.inventory_product_id) + [
            ("location_id", "=", location_id),
            ("quantity", "!=", 0),
        ]
        action["context"] = {
            "search_default_internal_loc": 1,
            "default_product_id": product_id,
            "default_location_id": location_id,
        }
        return action

    def action_add_inventory_product_line(self):
        """Add selected product to the order or increase its existing line quantity."""
        self.ensure_one()
        if not self.free_customizations_enabled:
            raise UserError(self.env._("This customization is not enabled for this company."))
        if not self.inventory_product_id:
            raise UserError(self.env._("Please choose a product first."))
        if self.inventory_product_qty <= 0:
            raise UserError(self.env._("Quantity must be greater than zero."))

        existing_line = self.order_line.filtered(
            lambda line: (
                not line.display_type
                and line.product_id == self.inventory_product_id
            )
        )[:1]
        if existing_line:
            existing_line.product_uom_qty += self.inventory_product_qty
        else:
            product_id = getattr(self.inventory_product_id, "id", False)
            self.env["sale.order.line"].create({
                "order_id": self.id,
                "product_id": product_id,
                "product_uom_qty": self.inventory_product_qty,
            })
        self.inventory_product_id = False
        self.inventory_product_qty = 1.0
        self.inventory_location_id = False
        return True
