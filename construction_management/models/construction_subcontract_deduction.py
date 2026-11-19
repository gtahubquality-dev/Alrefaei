"""Construction subcontract deduction for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import ValidationError

from .construction_common import (
    apply_deduction_type,
    check_deduction_values,
    compute_deduction_amount,
    contract_field,
)
from .construction_deduction_helpers import (
    applied_on_other_invoice,
    check_refundable_balance,
    compute_deduction_balances,
    deduction_account_field,
    deduction_policy_fields,
    deduction_refund_action,
)


class ConstructionSubcontractDeduction(models.Model):
    """Construction subcontract deduction."""

    _name = 'construction.subcontract.deduction'
    _description = 'Subcontract Variable Deduction'
    _order = 'contract_id, sequence, id'

    contract_id = contract_field()
    company_id = fields.Many2one(related='contract_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='contract_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    type_id = fields.Many2one(
        'construction.deduction.type',
        string='Deduction Type',
        domain="[('applies_to', 'in', ('subcontractor', 'both'))]",
    )
    project_deduction_id = fields.Many2one(
        'construction.project.deduction',
        string='Project Policy',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    name, kind, calculation, value, frequency = deduction_policy_fields()
    account_id = deduction_account_field(
        required=True,
        help="Account credited when the deduction is withheld from a subcontractor invoice.",
    )
    refundable = fields.Boolean(string='Refundable')
    invoice_deduction_ids = fields.One2many(
        'construction.subcontract.invoice.deduction',
        'contract_deduction_id',
        string='Applied Deductions',
    )
    deducted_amount = fields.Monetary(compute='_compute_balances', string='Total Deducted')
    refunded_amount = fields.Monetary(compute='_compute_balances', string='Total Refunded')
    balance = fields.Monetary(compute='_compute_balances', string='Balance to Refund')

    def _compute_balances(self):
        operations = self.env['construction.project.operation'].sudo()
        compute_deduction_balances(
            self,
            lambda line: line.invoice_id.state == 'finance_approved',
            operations,
            'sub_deduction_id',
            'sub_suspense_refund',
        )

    @api.onchange('type_id')
    def _onchange_type_id(self):
        apply_deduction_type(self)

    @api.constrains('value', 'calculation')
    def _check_value(self):
        check_deduction_values(self)

    @api.constrains('type_id')
    def _check_type_party(self):
        for deduction in self:
            if deduction.type_id and deduction.type_id.applies_to == 'owner':
                raise ValidationError(
                    _(
                        'Deduction type %s is reserved for customer contracts.',
                        deduction.type_id.name,
                    )
                )

    def _compute_amount_for(self, gross_amount):
        return compute_deduction_amount(self, gross_amount)

    def _applied_on_other_invoice(self, invoice):
        """Check other invoices of the contract for an existing deduction."""
        return applied_on_other_invoice(self, invoice, ('cancelled', 'rejected'))

    def action_refund(self):
        """Refund."""
        self.ensure_one()
        check_refundable_balance(self)
        return deduction_refund_action(
            self,
            default_project_id=self.contract_id.project_id.id,
            default_subcontract_id=self.contract_id.id,
            default_operation_type='sub_suspense_refund',
            default_sub_deduction_id=self.id,
        )
