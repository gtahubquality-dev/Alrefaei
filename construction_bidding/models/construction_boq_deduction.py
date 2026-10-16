"""Deduction snapshots linked to BOQs."""

from odoo import fields, models


class BOQDeduction(models.Model):
    """Commercial deduction line linked to a BOQ."""

    _name = "construction.boq.deduction"
    _description = "BOQ Deduction"
    _inherit = "construction.deduction.mixin"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    boq_id = fields.Many2one("construction.boq", required=True, ondelete="cascade")
