"""BOQ models for construction bidding."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero

from .boq_common import BOQ_ITEM_TYPES, form_action


class BiddingBOQLine(models.Model):
    """BOQ cost line."""

    _name = "construction.boq.line"
    _description = "BOQ Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    boq_id = fields.Many2one("construction.boq", required=True, ondelete="cascade")
    project_id = fields.Many2one(related="boq_id.project_id", store=True)
    currency_id = fields.Many2one(related="boq_id.currency_id")
    item_type = fields.Selection(BOQ_ITEM_TYPES, string="Type", required=True, default="main")
    description = fields.Text(required=True)
    quantity = fields.Float(default=1.0)
    original_quantity = fields.Float(copy=False, readonly=True)
    uom_id = fields.Many2one("uom.uom", string="UoM")
    unit_cost = fields.Monetary()
    total_cost = fields.Monetary(compute="_compute_total_cost", store=True)
    weight_percentage = fields.Float(string="Weight / Equivalency %")
    cost_percentage = fields.Float(string="Cost %", compute="_compute_cost_percentage", store=True)
    variation_line_ids = fields.One2many(
        "construction.variation.order.line",
        "boq_line_id",
        string="VO Lines",
    )

    product_id = fields.Many2one("product.product")
    item_id = fields.Many2one("construction.item", string="Item")
    planned_quantity = fields.Float(default=1.0)
    finished_product_id = fields.Many2one(
        "product.product", domain=[("type", "=", "service")],
    )
    parent_line_id = fields.Many2one(
        "construction.boq.line", ondelete="cascade", copy=False,
    )
    component_line_ids = fields.One2many("construction.boq.line", "parent_line_id", copy=False)

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.description = line.product_id.display_name
                line.uom_id = line.product_id.uom_id
                line.unit_cost = line.product_id.standard_price

    @api.onchange("item_id")
    def _onchange_item_id(self):
        for line in self:
            if line.item_id:
                line.product_id = line.item_id.product_id
                line.description = line.item_id.name
                line.uom_id = line.product_id.uom_id

    def action_set_quantity(self):
        """Replace this main item's components using its planned quantity."""
        for line in self:
            if line.item_type != "main" or not line.item_id:
                raise UserError(_("Select an Item on a main BOQ line first."))
            if float_is_zero(line.item_id.quantity, precision_digits=6):
                raise UserError(_("The configured Item quantity must be nonzero."))
            factor = line.planned_quantity / line.item_id.quantity
            values = []
            for item_type, components in (
                ("material", line.item_id.material_line_ids),
                ("subcontractor", line.item_id.subcontractor_line_ids),
                ("equipment", line.item_id.equipment_line_ids),
            ):
                for component in components:
                    vals = {
                        "boq_id": line.boq_id.id,
                        "parent_line_id": line.id,
                        "item_type": item_type,
                        "product_id": component.product_id.id,
                        "description": component.product_id.display_name,
                        "quantity": component.quantity * factor,
                        "uom_id": component.product_id.uom_id.id,
                        "unit_cost": component.product_id.standard_price,
                    }
                    if item_type == "subcontractor":
                        vals["finished_product_id"] = component.finished_product_id.id
                    values.append(vals)
            line.component_line_ids.unlink()
            self.env["construction.boq.line"].create(values)
            line.quantity = line.planned_quantity
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """Keep the original quantity at creation."""
        records = super().create(vals_list)
        for record in records:
            if not record.original_quantity:
                record.original_quantity = record.quantity
        return records

    @api.depends("quantity", "unit_cost")
    def _compute_total_cost(self):
        for line in self:
            line.total_cost = line.quantity * line.unit_cost

    @api.depends("total_cost", "boq_id.total_cost")
    def _compute_cost_percentage(self):
        for line in self:
            if line.boq_id.total_cost:
                line.cost_percentage = (line.total_cost / line.boq_id.total_cost) * 100
            else:
                line.cost_percentage = 0.0

    def action_view_boq(self):
        """Open the BOQ linked to this line."""
        self.ensure_one()
        return form_action("BOQ", "construction.boq", self.boq_id.id)
