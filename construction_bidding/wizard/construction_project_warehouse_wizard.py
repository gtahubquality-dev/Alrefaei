"""Warehouse short-name wizard for construction bidding."""

from odoo import fields, models

from ..models.boq_common import form_action


class ProjectWarehouseWizard(models.TransientModel):
    """Collect the project warehouse short name before approval."""

    _name = "construction.project.warehouse.wizard"
    _description = "Project Warehouse Short Name Wizard"

    project_id = fields.Many2one("project.project", required=True, readonly=True)
    short_name = fields.Char(string="Warehouse Short Name", required=True, size=5)
    create_boq = fields.Boolean()

    def action_confirm(self):
        """Create missing setup and continue optional BOQ creation."""
        self.ensure_one()
        self.project_id.ensure_cost_center()
        self.project_id.create_project_warehouse(self.short_name)
        self.project_id.bidding_state = "approved"
        if self.create_boq:
            return self.project_id.action_create_boq()
        return {"type": "ir.actions.act_window_close"}

    def action_view_project(self):
        """Open the related project."""
        self.ensure_one()
        return form_action("Project", "project.project", self.project_id.id)
