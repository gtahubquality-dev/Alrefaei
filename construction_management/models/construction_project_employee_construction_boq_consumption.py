"""Construction project employee construction boq consumption for construction management."""

from odoo import fields
from odoo import models


class ConstructionProjectEmployee(models.Model):
    """Construction project employee."""

    _inherit = 'construction.project.employee'

    boq_component_id = fields.Many2one(
        'construction.boq.component',
        string='BOQ Labor',
        index='btree_not_null',
        domain="[('project_id', '=', project_id), ('component_type', '=', 'labor')]",
        help=(
            "Labor line of the BOQ this worker is charged to: the labor cost allocations are posted"
            " on this BOQ item."
        ),
    )
