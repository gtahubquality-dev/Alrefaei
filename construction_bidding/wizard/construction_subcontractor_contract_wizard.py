"""Choose the subcontractor and quantities for a contract."""

from odoo import Command, _, fields, models
from odoo.exceptions import UserError


class ConstructionSubcontractorContractWizard(models.TransientModel):
    """Create Subcontractor Contract."""

    _name = "construction.subcontractor.contract.wizard"
    _description = "Create Subcontractor Contract"

    subcontractor_boq_id = fields.Many2one("construction.subcontractor.boq", required=True)
    partner_id = fields.Many2one("res.partner", string="Subcontractor", required=True)
    line_ids = fields.One2many("construction.subcontractor.contract.wizard.line", "wizard_id")

    def action_create_contract(self):
        """Create a contract from the selected positive distribution quantities."""
        self.ensure_one()
        selected = self.line_ids.filtered(lambda line: line.quantity > 0)
        if not selected:
            raise UserError(_("Enter a quantity for at least one subcontractor line."))
        contract = self.env["construction.subcontractor.contract"].create({
            "partner_id": self.partner_id.id,
            "subcontractor_boq_id": self.subcontractor_boq_id.id,
            "line_ids": [Command.create({
                "source_line_id": line.source_line_id.id,
                "quantity": line.quantity,
                "price_unit": line.source_line_id.unit_cost,
            }) for line in selected],
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "construction.subcontractor.contract",
            "res_id": contract.id,
            "view_mode": "form",
        }
