"""Project-based subcontractor quantities available for contracts."""

from odoo import Command, _, fields, models


class ConstructionSubcontractorBOQ(models.Model):
    """Subcontractor BOQ."""

    _name = "construction.subcontractor.boq"
    _description = "Subcontractor BOQ"
    _rec_name = "project_id"

    boq_id = fields.Many2one("construction.boq", required=True, ondelete="cascade")
    project_id = fields.Many2one(related="boq_id.project_id", store=True)
    company_id = fields.Many2one(related="boq_id.company_id", store=True)
    line_ids = fields.One2many("construction.subcontractor.boq.line", "subcontractor_boq_id")
    contract_ids = fields.One2many("construction.subcontractor.contract", "subcontractor_boq_id")

    def action_create_contract(self):
        """Choose a subcontractor and distribute the available quantities."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Create Subcontractor Contract"),
            "res_model": "construction.subcontractor.contract.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_subcontractor_boq_id": self.id,
                "default_line_ids": [Command.create({
                    "source_line_id": line.id,
                    "quantity": line.available_quantity,
                }) for line in self.line_ids if line.available_quantity > 0],
            },
        }
