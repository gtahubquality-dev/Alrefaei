"""Project extensions for construction bidding."""

from odoo import fields, models

from .boq_common import form_action


class ProjectDeduction(models.Model):
    """Commercial deduction line linked to a project."""

    _name = "construction.project.deduction"
    _description = "Project Deduction"
    _inherit = "construction.deduction.mixin"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    project_id = fields.Many2one("project.project", required=True, ondelete="cascade")
    def action_open_project(self):
        """Open the deduction project."""
        self.ensure_one()
        return form_action("Project", "project.project", self.project_id.id)
