"""Construction deduction type for construction management."""

from odoo import api
from odoo import fields
from odoo import models
from .construction_finance import DEDUCTION_FREQUENCIES, DEDUCTION_PARTIES

from .construction_common import check_deduction_values, deduction_calculation_field
from .construction_deduction_helpers import deduction_account_field, deduction_kind_field


class ConstructionDeductionType(models.Model):
    """Construction deduction type."""

    _name = 'construction.deduction.type'
    _description = 'Deduction Type'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company
    )
    kind = deduction_kind_field()
    calculation = deduction_calculation_field()
    value = fields.Float(string='Value', digits=(16, 4))
    frequency = fields.Selection(
        DEDUCTION_FREQUENCIES,
        string='Applied',
        required=True,
        default='every',
        help="Every invoice, or only once on the first invoice of the contract.",
    )
    applies_to = fields.Selection(
        DEDUCTION_PARTIES + [('both', 'Customer and Subcontractors')],
        string='Applies To',
        required=True,
        default='both',
        help="Contracts on which this deduction can be used.",
    )
    account_id = deduction_account_field(
        help=(
            "Account debited when the deduction is applied on an owner invoice, credited "
            "when it is withheld from a subcontractor invoice."
        ),
    )
    refundable = fields.Boolean(
        string='Refundable',
        help=(
            "Deducted amounts are kept as a balance and can be refunded later when conditions are"
            " met."
        ),
    )

    @api.onchange('kind')
    def _onchange_kind(self):
        for deduction in self:
            if deduction.kind == 'suspense':
                deduction.refundable = True

    @api.constrains('value', 'calculation')
    def _check_value(self):
        check_deduction_values(self)
