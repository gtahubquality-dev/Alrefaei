"""Material Request quantities imported from a BOQ."""

from odoo import fields, models


class ConstructionMaterialRequestLine(models.Model):
    """Material Request Line."""

    _name = "construction.material.request.line"
    _inherit = "construction.request.line.mixin"
    _description = "Material Request Line"

    request_id = fields.Many2one("construction.material.request", required=True, ondelete="cascade")
