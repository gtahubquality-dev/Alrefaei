"""Equipment Request quantities imported from a BOQ."""

from odoo import fields, models


class ConstructionEquipmentRequestLine(models.Model):
    """Equipment Request Line."""

    _name = "construction.equipment.request.line"
    _inherit = "construction.request.line.mixin"
    _description = "Equipment Request Line"

    request_id = fields.Many2one(
        "construction.equipment.request", required=True, ondelete="cascade",
    )
