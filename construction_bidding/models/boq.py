"""BOQ models for construction bidding."""

from odoo import api, fields, models

from .boq_common import BOQ_ITEM_TYPES, form_action


class BiddingBOQ(models.Model):
    """Bill of quantities linked to a project."""

    _name = "construction.boq"
    _description = "Bill of Quantities"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "project_id, id desc"

    name = fields.Char(required=True, tracking=True)
    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    partner_id = fields.Many2one(related="project_id.partner_id", store=True, string="Customer")
    currency_id = fields.Many2one(related="project_id.currency_id")
    line_ids = fields.One2many("construction.boq.line", "boq_id", string="BOQ Lines", copy=True)
    variation_order_ids = fields.One2many(
        "construction.variation.order",
        "boq_id",
        string="Variation Orders",
    )
    variation_order_count = fields.Integer(compute="_compute_variation_order_count")
    total_cost = fields.Monetary(compute="_compute_total_cost", store=True)

    @api.depends("line_ids.total_cost")
    def _compute_total_cost(self):
        for boq in self:
            boq.total_cost = sum(boq.line_ids.mapped("total_cost"))

    def _compute_variation_order_count(self):
        for boq in self:
            boq.variation_order_count = self.env["construction.variation.order"].search_count(
                [("boq_id", "=", boq.id)]
            )

    def action_view_variation_orders(self):
        """Open variation orders linked to this BOQ."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Variation Orders",
            "res_model": "construction.variation.order",
            "view_mode": "list,form",
            "domain": [("boq_id", "=", self.id)],
            "context": {
                "default_boq_id": self.id,
                "default_project_id": self.project_id.id,
            },
        }

    def action_view_project(self):
        """Open the project linked to this BOQ."""
        self.ensure_one()
        return form_action("Project", "project.project", self.project_id.id)


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
