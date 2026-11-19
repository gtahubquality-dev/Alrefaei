"""Account move line for construction management."""

from odoo import fields
from odoo import models
from .construction_boq import COST_TYPES


class AccountMoveLine(models.Model):
    """Account move line."""

    _inherit = 'account.move.line'

    construction_project_id = fields.Many2one(
        related='move_id.construction_project_id',
        store=True,
        string='Construction Project',
        index='btree_not_null',
    )
    construction_boq_item_id = fields.Many2one(
        'construction.boq.item', string='BOQ Item', index='btree_not_null', copy=False
    )
    construction_boq_component_id = fields.Many2one(
        'construction.boq.component',
        string='BOQ Cost Component',
        index='btree_not_null',
        copy=False,
    )
    construction_equipment_request_id = fields.Many2one(
        'construction.equipment.request',
        string='Equipment Request',
        index='btree_not_null',
        copy=False,
    )
    construction_cost_type = fields.Selection(
        COST_TYPES,
        string='Construction Cost Type',
        copy=False,
        help=(
            "Cost category of the line in the project cost report. Empty: deduced from the account."
        ),
    )
