"""Construction subcontract invoice deduction for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError

from .runtime import model_attribute

from .construction_common import check_deduction_amounts, invoice_field
from .construction_deduction_helpers import deduction_account_field


class ConstructionSubcontractInvoiceDeduction(models.Model):
    """Construction subcontract invoice deduction."""

    _name = 'construction.subcontract.invoice.deduction'
    _description = 'Subcontractor Invoice Deduction'
    _order = 'invoice_id, id'

    invoice_id = invoice_field()
    company_id = fields.Many2one(related='invoice_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='invoice_id.currency_id', string='Currency')
    contract_deduction_id = fields.Many2one(
        'construction.subcontract.deduction', string='Contract Deduction', ondelete='restrict'
    )
    kind = fields.Selection(related='contract_deduction_id.kind', string='Kind')
    is_manual = fields.Boolean(compute='_compute_is_manual', string='Manual')
    name = fields.Char(string='Description', required=True)
    account_id = deduction_account_field(required=True)
    amount = fields.Monetary(compute='_compute_amount', store=True, readonly=False, string='Amount')

    @api.depends('contract_deduction_id')
    def _compute_is_manual(self):
        for deduction in self:
            deduction.is_manual = not deduction.contract_deduction_id

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        deductions = super().create(vals_list)
        for deduction in deductions:
            if deduction.invoice_id.state not in ('draft', 'rejected'):
                raise UserError(_('Deductions can only be added to draft invoices.'))
        return deductions

    @api.depends('invoice_id.gross_amount', 'contract_deduction_id')
    def _compute_amount(self):
        for deduction in self:
            if deduction.contract_deduction_id:
                deduction.amount = model_attribute(
                    deduction.contract_deduction_id, '_compute_amount_for'
                )(deduction.invoice_id.gross_amount)
            else:
                deduction.amount = deduction.amount or 0.0

    @api.constrains('amount')
    def _check_amount(self):
        check_deduction_amounts(self)
