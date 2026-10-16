"""Select quantities to distribute to a subcontractor."""

from odoo import fields, models


class ConstructionSubcontractorContractWizardLine(models.TransientModel):
    """Subcontractor Contract Quantity."""

    _name = "construction.subcontractor.contract.wizard.line"
    _description = "Subcontractor Contract Quantity"

    wizard_id = fields.Many2one(
        "construction.subcontractor.contract.wizard", required=True, ondelete="cascade",
    )
    source_line_id = fields.Many2one("construction.subcontractor.boq.line", required=True)
    product_id = fields.Many2one(related="source_line_id.product_id")
    available_quantity = fields.Float(related="source_line_id.available_quantity")
    quantity = fields.Float()
