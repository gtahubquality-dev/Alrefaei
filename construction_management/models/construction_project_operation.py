"""Construction project operation for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .construction_common import (
    project_subcontract_field,
    restrict_project_field,
    workflow_status_field,
)
from .invoice_adjustments import journal_entry_action
from .runtime import model_attribute


class ConstructionProjectOperation(models.Model):
    """Construction project operation."""

    _name = 'construction.project.operation'
    _description = 'Project Financial Operation'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Description', required=True)
    project_id = restrict_project_field()
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    partner_id = fields.Many2one('res.partner', string='Partner', compute='_compute_partner_id')
    subcontract_id = project_subcontract_field()
    sub_deduction_id = fields.Many2one(
        'construction.subcontract.deduction',
        string='Subcontract Deduction',
        domain="[('contract_id', '=', subcontract_id), ('refundable', '=', True)]",
    )
    operation_type = fields.Selection(
        [
            ('advance_received', 'Advance Payment Received'),
            ('insurance_payment', 'Final Insurance Payment'),
            ('insurance_refund', 'Final Insurance Refund'),
            ('retention_refund', 'Work Guarantee Refund'),
            ('suspense_refund', 'Deduction / Suspense Refund'),
            ('sub_retention_refund', 'Subcontractor Work Guarantee Refund'),
            ('sub_suspense_refund', 'Subcontractor Deduction / Suspense Refund'),
        ],
        string='Operation',
        required=True,
        tracking=True,
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash', 'general'))]",
        help=(
            "Bank or cash journal for payments received or paid. Refunds use the construction"
            " miscellaneous journal."
        ),
    )
    deduction_id = fields.Many2one(
        'construction.project.deduction',
        string='Deduction',
        domain="[('project_id', '=', project_id), ('refundable', '=', True)]",
    )
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True, copy=False)
    state = workflow_status_field(
        [('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')]
    )

    @api.depends('project_id', 'subcontract_id', 'operation_type')
    def _compute_partner_id(self):
        for operation in self:
            if operation.operation_type in ('sub_retention_refund', 'sub_suspense_refund'):
                operation.partner_id = operation.subcontract_id.partner_id
            else:
                operation.partner_id = operation.project_id.partner_id

    @api.constrains('amount')
    def _check_amount(self):
        for operation in self:
            if float_compare(operation.amount, 0.0, precision_digits=6) <= 0:
                raise ValidationError(_('The operation amount must be positive.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_project_operation(self):
        for operation in self:
            if operation.state == 'posted':
                raise UserError(_('Posted financial operations cannot be deleted.'))

    def _get_payment_journal(self):
        self.ensure_one()
        journal = self.journal_id
        if not journal or journal.type not in ('bank', 'cash'):
            raise UserError(
                _('Please select a bank or cash journal for operation "%s".', self.name)
            )
        if not journal.default_account_id:
            raise UserError(_('Journal %s has no default account.', journal.name))
        return journal

    def _prepare_move_vals(self):
        self.ensure_one()
        project = self.project_id
        company = project.company_id
        if self.operation_type in ('sub_retention_refund', 'sub_suspense_refund'):
            return self._prepare_subcontract_move_vals()
        partner = project.partner_id.commercial_partner_id
        distribution = model_attribute(project, '_get_analytic_distribution')()
        amount = self.amount
        op_type = self.operation_type
        receivable = partner.with_company(company).property_account_receivable_id

        if op_type == 'advance_received':
            journal = self._get_payment_journal()
            debit_account = journal.default_account_id
            credit_account = model_attribute(project, '_get_company_account')(
                'construction_advance_account_id'
            )
        elif op_type == 'insurance_payment':
            journal = self._get_payment_journal()
            debit_account = model_attribute(project, '_get_company_account')(
                'construction_insurance_account_id'
            )
            credit_account = journal.default_account_id
        else:
            journal = (
                self.journal_id
                if self.journal_id.type == 'general'
                else model_attribute(project, '_get_misc_journal')()
            )
            if not receivable:
                raise UserError(_('Customer %s has no receivable account.', partner.display_name))
            debit_account = receivable
            if op_type == 'retention_refund':
                credit_account = model_attribute(project, '_get_company_account')(
                    'construction_retention_account_id'
                )
            elif op_type == 'insurance_refund':
                credit_account = model_attribute(project, '_get_company_account')(
                    'construction_insurance_account_id'
                )
            else:
                if not self.deduction_id:
                    raise UserError(_('Please select the deduction to refund.'))
                if (
                    float_compare(
                        amount,
                        self.deduction_id.balance,
                        precision_rounding=self.currency_id.rounding,
                    )
                    > 0
                ):
                    raise UserError(
                        _(
                            'The refund amount exceeds the deduction balance (%s).',
                            self.deduction_id.balance,
                        )
                    )
                credit_account = self.deduction_id.account_id

        label = f'{project.name} - {self.name}'
        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': label,
            'partner_id': partner.id,
            'construction_project_id': project.id,
            'line_ids': [
                (
                    0,
                    0,
                    {
                        'name': label,
                        'account_id': debit_account.id,
                        'partner_id': partner.id,
                        'debit': amount,
                        'credit': 0.0,
                        'analytic_distribution': distribution,
                    },
                ),
                (
                    0,
                    0,
                    {
                        'name': label,
                        'account_id': credit_account.id,
                        'partner_id': partner.id,
                        'debit': 0.0,
                        'credit': amount,
                        'analytic_distribution': distribution,
                    },
                ),
            ],
        }

    def _prepare_subcontract_move_vals(self):
        self.ensure_one()
        project = self.project_id
        contract = self.subcontract_id
        if not contract:
            raise UserError(_('Please select the subcontract.'))
        partner = contract.partner_id.commercial_partner_id
        payable = partner.with_company(project.company_id).property_account_payable_id
        if not payable:
            raise UserError(_('Subcontractor %s has no payable account.', partner.display_name))
        rounding = self.currency_id.rounding
        if self.operation_type == 'sub_retention_refund':
            if (
                float_compare(self.amount, contract.guarantee_balance, precision_rounding=rounding)
                > 0
            ):
                raise UserError(
                    _(
                        'The refund amount exceeds the work guarantee balance (%s).',
                        contract.guarantee_balance,
                    )
                )
            debit_account = model_attribute(project, '_get_company_account')(
                'construction_sub_retention_account_id'
            )
        else:
            if not self.sub_deduction_id:
                raise UserError(_('Please select the deduction to refund.'))
            if (
                float_compare(
                    self.amount, self.sub_deduction_id.balance, precision_rounding=rounding
                )
                > 0
            ):
                raise UserError(
                    _(
                        'The refund amount exceeds the deduction balance (%s).',
                        self.sub_deduction_id.balance,
                    )
                )
            debit_account = self.sub_deduction_id.account_id
        distribution = model_attribute(project, '_get_analytic_distribution')()
        journal = (
            self.journal_id
            if self.journal_id.type == 'general'
            else model_attribute(project, '_get_misc_journal')()
        )
        label = f'{contract.name} - {self.name}'
        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': label,
            'partner_id': partner.id,
            'construction_project_id': project.id,
            'line_ids': [
                (
                    0,
                    0,
                    {
                        'name': label,
                        'account_id': debit_account.id,
                        'partner_id': partner.id,
                        'debit': self.amount,
                        'credit': 0.0,
                        'analytic_distribution': distribution,
                    },
                ),
                (
                    0,
                    0,
                    {
                        'name': label,
                        'account_id': payable.id,
                        'partner_id': partner.id,
                        'debit': 0.0,
                        'credit': self.amount,
                        'analytic_distribution': distribution,
                    },
                ),
            ],
        }

    @api.onchange('operation_type', 'project_id')
    def _onchange_operation_type_amount(self):
        """Propose the amount still due according to the customer contract terms."""
        for operation in self:
            project = operation.project_id
            if not project or operation.amount:
                continue
            if operation.operation_type == 'advance_received' and project.advance_payment_amount:
                operation.amount = max(
                    project.advance_payment_amount - project.advance_received, 0.0
                )
            elif operation.operation_type == 'insurance_payment' and project.final_insurance_amount:
                operation.amount = max(project.final_insurance_amount - project.insurance_paid, 0.0)

    def _check_contract_terms(self):
        """The advance received / final insurance paid cannot exceed the amounts agreed in the
        customer contract."""
        for operation in self:
            project = operation.project_id
            project.invalidate_recordset(model_attribute(project, '_financial_fields')())
            rounding = operation.currency_id.rounding
            if operation.operation_type == 'advance_received' and project.advance_payment_amount:
                total = project.advance_received + operation.amount
                if (
                    float_compare(
                        total, project.advance_payment_amount, precision_rounding=rounding
                    )
                    > 0
                ):
                    raise UserError(
                        _(
                            'The advance received (%(total)s) would exceed the advance payment'
                            ' agreed in the customer contract (%(agreed)s).',
                            total=total,
                            agreed=project.advance_payment_amount,
                        )
                    )
            if operation.operation_type == 'insurance_payment' and project.final_insurance_amount:
                total = project.insurance_paid + operation.amount
                if (
                    float_compare(
                        total, project.final_insurance_amount, precision_rounding=rounding
                    )
                    > 0
                ):
                    raise UserError(
                        _(
                            'The final insurance paid (%(total)s) would exceed the final insurance'
                            ' of the customer contract (%(agreed)s).',
                            total=total,
                            agreed=project.final_insurance_amount,
                        )
                    )

    def action_post(self):
        """Post."""
        for operation in self:
            if operation.state != 'draft':
                raise UserError(_('Only draft operations can be posted.'))
            model_attribute(operation, '_check_contract_terms')()
            move = (
                self.env['account.move']
                .sudo()
                .with_company(operation.company_id)
                .create(model_attribute(operation, '_prepare_move_vals')())
            )
            move.action_post()
            operation.write({'move_id': move.id, 'state': 'posted'})
        return True

    def action_cancel(self):
        """Cancel."""
        for operation in self:
            if operation.state != 'draft':
                raise UserError(
                    _(
                        'Only draft operations can be cancelled. Reverse the posted journal entry'
                        ' from Accounting.'
                    )
                )
        self.write({'state': 'cancelled'})

    def action_view_move(self):
        """View move."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('No journal entry is linked to this operation.'))
        return journal_entry_action(self.move_id)
