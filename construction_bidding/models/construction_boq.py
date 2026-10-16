"""BOQ models for construction bidding."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .boq_common import form_action


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
    partner_id = fields.Many2one("res.partner", string="Client")
    currency_id = fields.Many2one(related="project_id.currency_id")
    line_ids = fields.One2many("construction.boq.line", "boq_id", string="BOQ Lines", copy=True)
    variation_order_ids = fields.One2many(
        "construction.variation.order",
        "boq_id",
        string="Variation Orders",
    )
    variation_order_count = fields.Integer(compute="_compute_variation_order_count")
    total_cost = fields.Monetary(compute="_compute_total_cost", store=True)

    planned_date = fields.Date()
    user_id = fields.Many2one("res.users", string="Project Manager")
    company_id = fields.Many2one(related="project_id.company_id", store=True)
    adjustment_type = fields.Selection(
        [("percentage", "Percentage"), ("fixed", "Fixed Amount")],
    )
    margin = fields.Float()
    final_insurance = fields.Float(string="Final Insurance %")
    retention_percentage = fields.Float(string="Retention Percentage %")
    advance_payment = fields.Float(string="Advance Payment %")
    deduction_line_ids = fields.One2many("construction.boq.deduction", "boq_id", copy=True)
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed")],
        default="draft", required=True, copy=False, tracking=True,
    )
    contract_id = fields.Many2one("subscription.contracts", readonly=True, copy=False)
    main_line_ids = fields.One2many(
        "construction.boq.line", "boq_id", domain=[("item_type", "=", "main")],
    )
    material_line_ids = fields.One2many(
        "construction.boq.line", "boq_id", domain=[("item_type", "=", "material")],
    )
    equipment_line_ids = fields.One2many(
        "construction.boq.line", "boq_id", domain=[("item_type", "=", "equipment")],
    )
    subcontractor_line_ids = fields.One2many(
        "construction.boq.line", "boq_id", domain=[("item_type", "=", "subcontractor")],
    )

    def action_confirm(self):
        """Create a sales contract containing only main BOQ items."""
        for boq in self:
            if boq.state == "confirmed":
                continue
            if any(not line.product_id for line in boq.main_line_ids):
                raise UserError(_("Select a product for each main item before confirming the BOQ."))
            contract = self.env["subscription.contracts"].with_company(
                boq.company_id or self.env.company,
            ).create({
                "name": boq.name,
                "reference": boq.name,
                "partner_id": boq.partner_id.id,
                "company_id": boq.company_id.id or self.env.company.id,
                "currency_id": boq.currency_id.id,
                "contract_line_ids": [Command.create({
                    "product_id": line.product_id.id,
                    "qty_ordered": line.quantity,
                    "price_unit": line.unit_cost,
                }) for line in boq.main_line_ids],
            })
            boq.write({"contract_id": contract.id, "state": "confirmed"})
            self._create_construction_requests(boq)
        return True

    def _create_construction_requests(self, boq):
        """Create material, equipment, and subcontractor requests from this BOQ."""
        for kind, model, lines in (
            ("material", "construction.material.request", boq.material_line_ids),
            ("equipment", "construction.equipment.request", boq.equipment_line_ids),
            ("subcontractor", "construction.subcontractor.boq", boq.subcontractor_line_ids),
        ):
            if not lines:
                continue
            self.env[model].create({
                "boq_id": boq.id,
                "line_ids": [Command.create({
                    "boq_line_id": line.id,
                    "product_id": line.product_id.id,
                    "description": line.description,
                    "quantity": line.quantity,
                    "uom_id": line.uom_id.id,
                    **({
                        "finished_product_id": line.finished_product_id.id,
                        "unit_cost": line.unit_cost,
                    } if kind == "subcontractor" else {}),
                }) for line in lines],
            })
        return True

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
