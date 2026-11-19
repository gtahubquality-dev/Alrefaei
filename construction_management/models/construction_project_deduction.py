"""Construction project deduction for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from .construction_finance import DEDUCTION_PARTIES

from .construction_common import (
    apply_deduction_type,
    check_deduction_values,
    compute_deduction_amount,
)
from .construction_deduction_helpers import (
    applied_on_other_invoice,
    check_refundable_balance,
    compute_deduction_balances,
    deduction_account_field,
    deduction_policy_fields,
    deduction_refund_action,
)


class ConstructionProjectDeduction(models.Model):
    """Construction project deduction."""

    _name = 'construction.project.deduction'
    _description = 'Project Deduction Policy'
    _order = 'project_id, applies_to, sequence, id'

    project_id = fields.Many2one(
        'construction.project', string='Project', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    applies_to = fields.Selection(
        DEDUCTION_PARTIES,
        string='Applies To',
        required=True,
        default='owner',
        help=(
            "Customer: deducted on the owner invoices of the project. Subcontractors: policy copied"
            " to every subcontract of the project, where it is deducted on the subcontractor"
            " invoices."
        ),
    )
    type_id = fields.Many2one(
        'construction.deduction.type',
        string='Deduction Type',
        domain="[('applies_to', 'in', (applies_to, 'both'))]",
    )
    name, kind, calculation, value, frequency = deduction_policy_fields()
    account_id = deduction_account_field(required=True)
    refundable = fields.Boolean(string='Refundable')
    invoice_deduction_ids = fields.One2many(
        'construction.owner.invoice.deduction', 'project_deduction_id', string='Applied Deductions'
    )
    deducted_amount = fields.Monetary(compute='_compute_balances', string='Total Deducted')
    refunded_amount = fields.Monetary(compute='_compute_balances', string='Total Refunded')
    balance = fields.Monetary(compute='_compute_balances', string='Balance to Refund')

    def _compute_balances(self):
        operations = self.env['construction.project.operation']
        compute_deduction_balances(
            self,
            lambda line: line.invoice_id.state == 'invoiced'
            and line.invoice_id.sudo().move_id.state == 'posted',
            operations,
            'deduction_id',
            'suspense_refund',
        )

    @api.onchange('type_id')
    def _onchange_type_id(self):
        apply_deduction_type(self)

    @api.constrains('value', 'calculation')
    def _check_value(self):
        check_deduction_values(self)

    @api.constrains('type_id', 'applies_to')
    def _check_type_party(self):
        for deduction in self:
            if deduction.type_id and deduction.type_id.applies_to not in (
                deduction.applies_to,
                'both',
            ):
                raise ValidationError(
                    _(
                        'Deduction type %(type)s cannot be used for %(party)s.',
                        type=deduction.type_id.name,
                        party=dict(DEDUCTION_PARTIES)[deduction.applies_to],
                    )
                )

    def write(self, vals):
        """Write."""
        if 'applies_to' in vals:
            for deduction in self:
                if deduction.applies_to != vals['applies_to'] and deduction.invoice_deduction_ids:
                    raise UserError(
                        _(
                            'Deduction %s is already applied on owner invoices: its party cannot'
                            ' change.',
                            deduction.name,
                        )
                    )
        return super().write(vals)

    def _compute_amount_for(self, gross_amount):
        return compute_deduction_amount(self, gross_amount)

    def _applied_on_other_invoice(self, invoice):
        """True when this deduction is already deducted on another non cancelled owner invoice."""
        return applied_on_other_invoice(self, invoice, ('cancelled',))

    def _subcontract_deduction_vals(self):
        """Values of the subcontract deduction created from this project policy line."""
        self.ensure_one()
        return {
            'project_deduction_id': self.id,
            'sequence': self.sequence,
            'type_id': self.type_id.id,
            'name': self.name,
            'kind': self.kind,
            'calculation': self.calculation,
            'value': self.value,
            'frequency': self.frequency,
            'account_id': self.account_id.id,
            'refundable': self.refundable,
        }

    def action_refund(self):
        """Refund."""
        self.ensure_one()
        if self.applies_to != 'owner':
            raise UserError(_('Subcontractor deductions are refunded from the subcontract.'))
        check_refundable_balance(self)
        return deduction_refund_action(
            self,
            default_project_id=self.project_id.id,
            default_operation_type='suspense_refund',
            default_deduction_id=self.id,
        )
