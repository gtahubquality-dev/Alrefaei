"""Shared fields and calculations for owner and subcontract deductions."""

from odoo import _, fields
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

from .construction_common import deduction_calculation_field, deduction_frequency_field
from .construction_finance import DEDUCTION_KINDS


def deduction_kind_field():
    """Create the kind field for a deduction or its policy type."""
    return fields.Selection(DEDUCTION_KINDS, string='Kind', required=True, default='tax')


def deduction_policy_fields():
    """Create the description, kind, calculation, value, and frequency fields."""
    return (
        fields.Char(string='Description', required=True),
        deduction_kind_field(),
        deduction_calculation_field(),
        fields.Float(string='Value', digits=(16, 4)),
        deduction_frequency_field(),
    )


def deduction_account_field(**options):
    """Create an account field excluding receivable, payable, and inactive accounts."""
    return fields.Many2one(
        'account.account',
        string='Account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), "
            "('active', '=', True)]"
        ),
        **options,
    )


def compute_deduction_balances(deductions, applied_invoice, operations, link_field, operation_type):
    """Update withheld amounts, completed refunds, and refundable balances."""
    for deduction in deductions:
        applied = deduction.invoice_deduction_ids.filtered(applied_invoice)
        deduction.deducted_amount = sum(applied.mapped('amount'))
        refunded = 0.0
        if deduction.id:
            refunded = sum(
                operations.search(
                    [
                        (link_field, '=', deduction.id),
                        ('operation_type', '=', operation_type),
                        ('state', '=', 'posted'),
                    ]
                ).mapped('amount')
            )
        deduction.refunded_amount = refunded
        deduction.balance = deduction.deducted_amount - refunded if deduction.refundable else 0.0


def applied_on_other_invoice(deduction, invoice, excluded_states):
    """Check whether another invoice already contains a positive deduction."""
    deduction.ensure_one()
    return bool(
        deduction.invoice_deduction_ids.filtered(
            lambda line: line.invoice_id != invoice
            and line.invoice_id.state not in excluded_states
            and line.amount > 0
        )
    )


def check_refundable_balance(self):
    """Require a refundable deduction with a positive balance."""
    if not self.refundable:
        raise UserError(_('Deduction %s is not refundable.', self.name))
    if (
        float_is_zero(self.balance, precision_rounding=self.currency_id.rounding)
        or self.balance < 0
    ):
        raise UserError(_('There is no balance to refund for %s.', self.name))


def deduction_refund_action(self, **defaults):
    """Open the project operation form for the deduction refund."""
    return {
        'type': 'ir.actions.act_window',
        'name': _('Refund Deduction'),
        'res_model': 'construction.project.operation',
        'view_mode': 'form',
        'target': 'current',
        'context': {
            **defaults,
            'default_amount': self.balance,
            'default_name': _('Refund of %s', self.name),
        },
    }
