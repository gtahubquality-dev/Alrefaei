"""Project extensions for construction bidding."""

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .boq_common import form_action


class ProjectProject(models.Model):
    """Add bidding contract data to projects."""

    _inherit = "project.project"

    project_code = fields.Char(string="Project Code", tracking=True)
    project_duration_months = fields.Integer(string="Project Duration (Months)", tracking=True)
    scheduled_end_date = fields.Date(
        string="Scheduled End Date",
        compute="_compute_scheduled_end_date",
        store=True,
    )
    project_handover_date = fields.Date(string="Project Handover Date", tracking=True)
    project_owner_id = fields.Many2one(
        "res.partner",
        string="Project Owner / Entity",
        domain="['|', ('company_id', '=?', company_id), ('company_id', '=', False)]",
        tracking=True,
    )
    consultant_id = fields.Many2one(
        "res.partner",
        string="Consultant",
        domain="['|', ('company_id', '=?', company_id), ('company_id', '=', False)]",
        tracking=True,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Project Warehouse",
        copy=False,
        check_company=True,
        tracking=True,
    )
    final_insurance = fields.Float(string="Final Insurance %", tracking=True)
    retention_percentage = fields.Float(string="Retention Percentage %", tracking=True)
    advance_payment = fields.Float(string="Advance Payment %", tracking=True)
    bidding_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
        ],
        string="Bidding Status",
        default="draft",
        required=True,
        tracking=True,
    )
    deduction_line_ids = fields.One2many(
        "construction.project.deduction",
        "project_id",
        string="Deductions",
        copy=True,
    )
    boq_ids = fields.One2many("construction.boq", "project_id", string="BOQs")
    boq_count = fields.Integer(compute="_compute_boq_count", string="BOQ Count")

    @api.depends("date_start", "project_duration_months")
    def _compute_scheduled_end_date(self):
        for project in self:
            if project.date_start and project.project_duration_months:
                project.scheduled_end_date = project.date_start + relativedelta(
                    months=project.project_duration_months
                )
            else:
                project.scheduled_end_date = False

    def _compute_boq_count(self):
        for project in self:
            project.boq_count = self.env["construction.boq"].search_count(
                [("project_id", "=", project.id)]
            )

    def _get_default_analytic_plan(self):
        plan = self.env.ref("analytic.analytic_plan_projects", raise_if_not_found=False)
        return plan or self.env["account.analytic.plan"].search([], limit=1)

    def ensure_cost_center(self):
        """Create the project analytic account when it is missing."""
        for project in self:
            if project.account_id:
                continue
            plan = self._get_default_analytic_plan()
            if not plan:
                raise UserError(
                    _("Please configure an Analytic Plan before approving the project.")
                )
            project.account_id = self.env["account.analytic.account"].create({
                "name": project.name,
                "code": project.project_code,
                "plan_id": plan.id,
                "company_id": project.company_id.id or self.env.company.id,
                "partner_id": project.partner_id.id,
            })

    def create_project_warehouse(self, short_name):
        """Create and link the project warehouse."""
        self.ensure_one()
        if self.warehouse_id:
            return self.warehouse_id
        if not short_name:
            raise UserError(_("Warehouse Short Name is required."))
        self.warehouse_id = self.env["stock.warehouse"].create({
            "name": self.name,
            "code": short_name[:5].upper(),
            "company_id": self.company_id.id or self.env.company.id,
            "partner_id": self.partner_id.id or self.env.company.partner_id.id,
        })
        return self.warehouse_id

    def action_open_warehouse_short_name_wizard(self):
        """Open the warehouse short-name wizard."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Project Warehouse Short Name"),
            "res_model": "construction.project.warehouse.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_project_id": self.id,
                "default_short_name": (self.project_code or self.name or "")[:5].upper(),
                "default_create_boq": self.env.context.get("create_boq_after_approval", False),
            },
        }

    def action_approve_bidding_project(self):
        """Approve bidding project and create missing financial setup."""
        for project in self:
            project.ensure_cost_center()
            if not project.warehouse_id:
                return project.action_open_warehouse_short_name_wizard()
            project.bidding_state = "approved"
        return True

    def action_set_in_progress(self):
        """Move the bidding project to in progress."""
        self.write({"bidding_state": "in_progress"})
        return True

    def action_set_completed(self):
        """Move the bidding project to completed."""
        self.write({"bidding_state": "completed"})
        return True

    def action_create_boq(self):
        """Create a BOQ and approve the project when needed."""
        self.ensure_one()
        if self.bidding_state == "completed":
            raise UserError(_("You cannot create a BOQ for a completed project."))
        if self.bidding_state == "draft":
            approval_result = self.with_context(
                create_boq_after_approval=True
            ).action_approve_bidding_project()
            if isinstance(approval_result, dict):
                return approval_result
        boq = self.env["construction.boq"].create({
            "name": _("BOQ - %s", self.name),
            "project_id": self.id,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("BOQ"),
            "res_model": "construction.boq",
            "res_id": boq.id,
            "view_mode": "form",
        }

    def action_view_boqs(self):
        """Open BOQs linked to the project."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("BOQs"),
            "res_model": "construction.boq",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }


class ProjectDeduction(models.Model):
    """Commercial deduction line linked to a project."""

    _name = "construction.project.deduction"
    _description = "Project Deduction"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    project_id = fields.Many2one("project.project", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", string="Product", required=True)
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="UoM",
        required=True,
    )
    price_unit = fields.Float(string="Price")

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.product_uom_id = line.product_id.uom_id
                line.price_unit = line.product_id.lst_price

    def action_open_product(self):
        """Open the deduction product."""
        self.ensure_one()
        return form_action("Product", "product.product", self.product_id.id)

    def action_open_project(self):
        """Open the deduction project."""
        self.ensure_one()
        return form_action("Project", "project.project", self.project_id.id)
