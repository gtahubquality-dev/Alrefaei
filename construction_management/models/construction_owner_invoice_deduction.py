"""Construction owner invoice deduction for construction management."""

from odoo import api
from odoo import fields
from odoo import models

from .runtime import model_attribute

from .construction_common import check_deduction_amounts, owner_invoice_field


class ConstructionOwnerInvoiceDeduction(models.Model):
    """Construction owner invoice deduction."""

    _name = 'construction.owner.invoice.deduction'
    _description = 'Owner Invoice Deduction'
    _order = 'invoice_id, id'

    invoice_id = owner_invoice_field()
    company_id = fields.Many2one(related='invoice_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='invoice_id.currency_id', string='Currency')
    project_deduction_id = fields.Many2one(
        'construction.project.deduction', string='Project Deduction', ondelete='restrict'
    )
    kind = fields.Selection(related='project_deduction_id.kind', string='Kind')
    refundable = fields.Boolean(related='project_deduction_id.refundable', string='Refundable')
    name = fields.Char(string='Description', required=True)
    account_id = fields.Many2one('account.account', string='Account', required=True)
    amount = fields.Monetary(compute='_compute_amount', store=True, readonly=False, string='Amount')

    @api.depends('invoice_id.gross_amount', 'project_deduction_id')
    def _compute_amount(self):
        for deduction in self:
            if deduction.project_deduction_id:
                deduction.amount = model_attribute(
                    deduction.project_deduction_id, '_compute_amount_for'
                )(deduction.invoice_id.gross_amount)
            else:
                deduction.amount = deduction.amount or 0.0

    @api.constrains('amount')
    def _check_amount(self):
        check_deduction_amounts(self)
