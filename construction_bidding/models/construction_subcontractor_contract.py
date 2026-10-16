"""Subcontractor contracts distributed from a project BOQ."""

from odoo import fields, models


class ConstructionSubcontractorContract(models.Model):
    """Subcontractor Contract."""

    _name = "construction.subcontractor.contract"
    _description = "Subcontractor Contract"
    _rec_name = "partner_id"

    partner_id = fields.Many2one("res.partner", string="Subcontractor", required=True)
    subcontractor_boq_id = fields.Many2one(
        "construction.subcontractor.boq", required=True, ondelete="restrict",
    )
    project_id = fields.Many2one(related="subcontractor_boq_id.project_id", store=True)
    boq_id = fields.Many2one(related="subcontractor_boq_id.boq_id", store=True)
    company_id = fields.Many2one(related="subcontractor_boq_id.company_id", store=True)
    currency_id = fields.Many2one(related="boq_id.currency_id")
    line_ids = fields.One2many("construction.subcontractor.contract.line", "contract_id")
