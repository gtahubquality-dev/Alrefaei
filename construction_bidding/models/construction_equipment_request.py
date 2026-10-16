"""Equipment Requests from confirmed BOQs."""

from odoo import fields, models


class ConstructionEquipmentRequest(models.Model):
    """Equipment Request."""

    _name = "construction.equipment.request"
    _description = "Equipment Request"
    _rec_name = "boq_id"

    boq_id = fields.Many2one("construction.boq", required=True, ondelete="cascade")
    project_id = fields.Many2one(related="boq_id.project_id", store=True)
    company_id = fields.Many2one(related="boq_id.company_id", store=True)
    line_ids = fields.One2many("construction.equipment.request.line", "request_id")
