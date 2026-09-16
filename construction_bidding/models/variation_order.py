"""Variation order models for construction bidding."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .boq_common import BOQ_ITEM_TYPES, form_action


class VariationOrder(models.Model):
    """Variation order that changes a BOQ through traceable lines."""

    _name = "construction.variation.order"
    _description = "Variation Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "change_date desc, id desc"

    name = fields.Char(required=True, default=lambda self: _("New"), tracking=True)
    project_id = fields.Many2one("project.project", required=True, tracking=True)
    boq_id = fields.Many2one(
        "construction.boq",
        required=True,
        tracking=True,
        domain="[('project_id', '=', project_id)]",
    )
    change_date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    changed_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    line_ids = fields.One2many(
        "construction.variation.order.line",
        "variation_order_id",
        string="Lines",
        copy=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("applied", "Applied")],
        default="draft",
        required=True,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the VO sequence."""
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = sequence.next_by_code("construction.variation.order") or _("New")
        return super().create(vals_list)

    @api.onchange("boq_id")
    def _onchange_boq_id(self):
        for order in self:
            if order.boq_id:
                order.project_id = order.boq_id.project_id

    def action_apply(self):
        """Apply VO lines to the linked BOQ."""
        for order in self:
            if order.state == "applied":
                continue
            if not order.line_ids:
                raise UserError(_("Please add at least one variation order line."))
            for line in order.line_ids:
                line.apply_to_boq()
            order.write({
                "state": "applied",
                "change_date": fields.Datetime.now(),
                "changed_by_id": self.env.user.id,
            })
        return True

    def action_view_boq(self):
        """Open the BOQ linked to this VO."""
        self.ensure_one()
        return form_action("BOQ", "construction.boq", self.boq_id.id)


class VariationOrderLine(models.Model):
    """Single BOQ change requested by a variation order."""

    _name = "construction.variation.order.line"
    _description = "Variation Order Line"
    _order = "id"

    variation_order_id = fields.Many2one(
        "construction.variation.order",
        required=True,
        ondelete="cascade",
    )
    project_id = fields.Many2one(related="variation_order_id.project_id", store=True)
    boq_id = fields.Many2one(related="variation_order_id.boq_id", store=True)
    change_type = fields.Selection(
        [("increase_quantity", "Increase Quantity"), ("new_item", "New Item")],
        required=True,
        default="increase_quantity",
    )
    boq_line_id = fields.Many2one(
        "construction.boq.line",
        string="Existing BOQ Line",
        domain="[('boq_id', '=', boq_id)]",
    )
    new_boq_line_id = fields.Many2one(
        "construction.boq.line",
        string="Created BOQ Line",
        readonly=True,
        copy=False,
    )
    item_type = fields.Selection(BOQ_ITEM_TYPES, string="Type", default="main")
    description = fields.Text()
    increase_quantity = fields.Float(string="Quantity Increase")
    original_quantity = fields.Float(readonly=True, copy=False)
    new_quantity = fields.Float(readonly=True, copy=False)
    uom_id = fields.Many2one("uom.uom", string="UoM")
    unit_cost = fields.Monetary()
    currency_id = fields.Many2one(related="variation_order_id.boq_id.currency_id")
    change_date = fields.Datetime(related="variation_order_id.change_date", store=True)
    changed_by_id = fields.Many2one(related="variation_order_id.changed_by_id", store=True)

    @api.onchange("boq_line_id")
    def _onchange_boq_line_id(self):
        for line in self:
            if line.boq_line_id:
                line.description = line.boq_line_id.description
                line.uom_id = line.boq_line_id.uom_id
                line.unit_cost = line.boq_line_id.unit_cost

    def apply_to_boq(self):
        """Apply this line to the target BOQ."""
        self.ensure_one()
        if self.change_type == "increase_quantity":
            if not self.boq_line_id:
                raise UserError(_("Select an existing BOQ line to increase quantity."))
            self.original_quantity = self.boq_line_id.quantity
            self.new_quantity = self.boq_line_id.quantity + self.increase_quantity
            self.boq_line_id.quantity = self.new_quantity
            return

        values = {
            "boq_id": self.boq_id.id,
            "item_type": self.item_type or "main",
            "description": self.description,
            "quantity": self.increase_quantity,
            "uom_id": self.uom_id.id,
            "unit_cost": self.unit_cost,
        }
        new_line = self.env["construction.boq.line"].create(values)
        self.write({
            "new_boq_line_id": new_line.id,
            "original_quantity": 0.0,
            "new_quantity": new_line.quantity,
        })

    def action_view_variation_order(self):
        """Open the parent variation order."""
        self.ensure_one()
        return form_action(
            "Variation Order",
            "construction.variation.order",
            self.variation_order_id.id,
        )
