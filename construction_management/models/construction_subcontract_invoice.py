"""Construction subcontract invoice for construction management."""

from odoo import Command
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.tools import float_compare
from odoo.tools import float_is_zero

from .construction_common import (
    active_contract_field,
    append_invoice_deductions,
    contract_related_field,
    reference_field,
    workflow_status_field,
)
from .invoice_adjustments import adjustment_account, adjustment_line, journal_entry_action
from .runtime import model_attribute


class ConstructionSubcontractInvoice(models.Model):
    """Construction subcontract invoice."""

    _name = 'construction.subcontract.invoice'
    _description = 'Subcontractor Invoice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = reference_field()
    contract_id = active_contract_field()
    date = fields.Date(string='Invoice Date', required=True, default=fields.Date.context_today)
    project_id = contract_related_field('project_id', 'Project')
    partner_id = contract_related_field('partner_id', 'Subcontractor')
    company_id = contract_related_field('company_id', 'Company')
    currency_id = contract_related_field('currency_id', 'Currency', store=False)
    vendor_reference = fields.Char(string='Subcontractor Invoice No.')
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('site_approved', 'Approved by Site'),
            ('mgmt_approved', 'Approved by Management'),
            ('finance_approved', 'Audited by Finance'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ]
    )
    line_ids = fields.One2many(
        'construction.subcontract.invoice.line', 'invoice_id', string='Lines', copy=True
    )

    site_approved_by_id = fields.Many2one(
        'res.users', string='Site Engineer', readonly=True, copy=False
    )
    site_approved_date = fields.Datetime(string='Site Approval Date', readonly=True, copy=False)
    mgmt_approved_by_id = fields.Many2one(
        'res.users', string='Senior Management', readonly=True, copy=False
    )
    mgmt_approved_date = fields.Datetime(
        string='Management Approval Date', readonly=True, copy=False
    )
    finance_approved_by_id = fields.Many2one(
        'res.users', string='Finance Auditor', readonly=True, copy=False
    )
    finance_approved_date = fields.Datetime(
        string='Finance Approval Date', readonly=True, copy=False
    )
    rejection_reason = fields.Text(string='Rejection Reason', copy=False)

    gross_amount = fields.Monetary(compute='_compute_gross', store=True, string='Gross Amount')
    guarantee_amount = fields.Monetary(
        compute='_compute_amounts', store=True, string='Work Guarantee'
    )
    advance_deduction_amount = fields.Monetary(
        compute='_compute_amounts', store=True, string='Advance Deduction'
    )
    deduction_ids = fields.One2many(
        'construction.subcontract.invoice.deduction', 'invoice_id', string='Deductions'
    )
    deduction_total = fields.Monetary(
        compute='_compute_amounts', store=True, string='Variable Deductions'
    )
    net_amount = fields.Monetary(compute='_compute_amounts', store=True, string='Net Amount')
    move_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False)
    payment_state = fields.Selection(related='move_id.payment_state', string='Payment Status')

    @api.depends('line_ids.amount')
    def _compute_gross(self):
        for invoice in self:
            invoice.gross_amount = sum(invoice.line_ids.mapped('amount'))

    @api.depends('gross_amount', 'deduction_ids.amount')
    def _compute_amounts(self):
        for invoice in self:
            currency = invoice.currency_id or self.env.company.currency_id
            gross = invoice.gross_amount
            contract = invoice.contract_id
            invoice.guarantee_amount = currency.round(gross * contract.guarantee_percent / 100.0)
            advance = currency.round(gross * contract.advance_deduction_percent / 100.0)
            available = 0.0
            if contract.advance_move_id:
                others = contract.invoice_ids.filtered(
                    lambda inv, current=invoice: inv.id != model_attribute(current, '_origin').id
                    and inv.state in ('site_approved', 'mgmt_approved', 'finance_approved')
                )
                available = contract.advance_amount - sum(others.mapped('advance_deduction_amount'))
            invoice.advance_deduction_amount = min(advance, max(available, 0.0))
            invoice.deduction_total = sum(invoice.deduction_ids.mapped('amount'))
            invoice.net_amount = (
                gross
                - invoice.guarantee_amount
                - invoice.advance_deduction_amount
                - invoice.deduction_total
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.subcontract.invoice'
                ) or _('New')
        invoices = super().create(vals_list)

        invoices.filtered(
            lambda inv: inv.state == 'draft' and inv.contract_id and not inv.line_ids
        ).action_generate_lines()
        model_attribute(invoices, '_refresh_previous')()
        return invoices

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        """New invoice: show the items of the selected contract right away."""
        for invoice in self:
            if model_attribute(invoice, '_origin') or invoice.state != 'draft':
                continue
            commands = [Command.clear()]
            commands += [
                Command.create({'contract_line_id': line.id, 'current_quantity': 0.0})
                for line in invoice.contract_id.line_ids
            ]
            invoice.line_ids = commands

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_subcontract_invoice(self):
        for invoice in self:
            if invoice.state not in ('draft', 'cancelled', 'rejected'):
                raise UserError(_('Only draft, rejected or cancelled invoices can be deleted.'))

    def _refresh_previous(self):
        line_model = self.env['construction.subcontract.invoice.line']
        for invoice in self.filtered(lambda inv: inv.state in ('draft', 'rejected')):
            for line in invoice.line_ids:
                previous = line_model.search(
                    [
                        ('contract_line_id', '=', line.contract_line_id.id),
                        ('invoice_id', '!=', invoice.id),
                        (
                            'invoice_id.state',
                            'in',
                            ('site_approved', 'mgmt_approved', 'finance_approved'),
                        ),
                    ]
                )
                line.previous_quantity = sum(previous.mapped('current_quantity'))

    def action_generate_lines(self):
        """Generate lines."""
        for invoice in self:
            if invoice.state != 'draft':
                raise UserError(_('Lines can only be generated on draft invoices.'))
            existing = invoice.line_ids.contract_line_id
            vals_list = [
                {
                    'invoice_id': invoice.id,
                    'contract_line_id': line.id,
                    'current_quantity': 0.0,
                }
                for line in invoice.contract_id.line_ids
                if line not in existing
            ]
            if vals_list:
                self.env['construction.subcontract.invoice.line'].create(vals_list)
            model_attribute(invoice, '_refresh_previous')()
            invoice.action_compute_deductions()
        return True

    def action_compute_deductions(self):
        """Recompute the deductions of the contract policy. Manual deductions (entered on the
        invoice) are kept."""
        for invoice in self:
            if invoice.state not in ('draft', 'rejected'):
                raise UserError(_('Deductions can only be recomputed on draft invoices.'))
            invoice.deduction_ids.filtered('contract_deduction_id').unlink()
            policy = invoice.contract_id.deduction_ids.filtered(
                lambda deduction, current=invoice: deduction.frequency == 'every'
                or not model_attribute(deduction, '_applied_on_other_invoice')(current)
            )
            vals_list = [
                {
                    'invoice_id': invoice.id,
                    'contract_deduction_id': deduction.id,
                    'name': deduction.name,
                    'account_id': deduction.account_id.id,
                }
                for deduction in policy
            ]
            if vals_list:
                self.env['construction.subcontract.invoice.deduction'].create(vals_list)
        return True

    def _check_deductions(self):
        for invoice in self:
            for line in invoice.deduction_ids:
                if not line.account_id:
                    raise UserError(_('Please set an account on deduction %s.', line.name))
                deduction = line.contract_deduction_id
                if (
                    deduction.frequency == 'once'
                    and line.amount > 0
                    and model_attribute(deduction, '_applied_on_other_invoice')(invoice)
                ):
                    raise UserError(
                        _(
                            'Deduction "%(name)s" is applied only once and is already on another'
                            ' invoice of contract %(contract)s. Recompute the deductions of'
                            ' %(invoice)s.',
                            name=line.name,
                            contract=invoice.contract_id.name,
                            invoice=invoice.name,
                        )
                    )

    def _check_quantities(self):
        for invoice in self:
            if not invoice.line_ids.filtered(lambda l: l.current_quantity > 0):
                raise UserError(_('Invoice %s has no executed quantity.', invoice.name))
            for line in invoice.line_ids:
                if line.current_quantity < 0:
                    raise ValidationError(_('Executed quantities cannot be negative.'))
                if (
                    float_compare(
                        line.previous_quantity + line.current_quantity,
                        line.contract_quantity,
                        precision_digits=4,
                    )
                    > 0
                ):
                    raise ValidationError(
                        _(
                            'Cumulative quantity of %(item)s exceeds the contract quantity'
                            ' (%(qty)s).',
                            item=line.contract_line_id.boq_item_id.display_name,
                            qty=line.contract_quantity,
                        )
                    )

    def action_site_approve(self):
        """Site approve."""
        if not self.env.user.has_group('construction_management.group_construction_user'):
            raise UserError(_('Only site engineers can approve invoices on site.'))
        for invoice in self:
            if invoice.state != 'draft':
                raise UserError(_('Only draft invoices can be approved on site.'))
            if invoice.contract_id.state != 'active':
                raise UserError(_('The contract of invoice %s is not active.', invoice.name))
            model_attribute(invoice, '_refresh_previous')()
            model_attribute(invoice, '_check_quantities')()
            if (
                invoice.contract_id.deduction_ids
                and not invoice.deduction_ids.contract_deduction_id
            ):
                invoice.action_compute_deductions()
            model_attribute(invoice, '_check_deductions')()
            self.env.add_to_compute(self._fields['net_amount'], invoice)
        self.write(
            {
                'state': 'site_approved',
                'site_approved_by_id': self.env.user.id,
                'site_approved_date': fields.Datetime.now(),
                'rejection_reason': False,
            }
        )
        return True

    def action_mgmt_approve(self):
        """Mgmt approve."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can approve at this stage.'))
        for invoice in self:
            if invoice.state != 'site_approved':
                raise UserError(_('Invoice %s must be approved on site first.', invoice.name))
        self.write(
            {
                'state': 'mgmt_approved',
                'mgmt_approved_by_id': self.env.user.id,
                'mgmt_approved_date': fields.Datetime.now(),
            }
        )
        return True

    def action_finance_approve(self):
        """Finance approve."""
        if not self.env.user.has_group('construction_management.group_construction_finance'):
            raise UserError(_('Only the Finance Department can audit subcontractor invoices.'))
        for invoice in self:
            if invoice.state != 'mgmt_approved':
                raise UserError(
                    _('Invoice %s must be approved by Senior Management first.', invoice.name)
                )
            move = (
                self.env['account.move']
                .sudo()
                .with_company(invoice.company_id)
                .create(model_attribute(invoice, '_prepare_bill_vals')())
            )
            invoice.write(
                {
                    'move_id': move.id,
                    'state': 'finance_approved',
                    'finance_approved_by_id': self.env.user.id,
                    'finance_approved_date': fields.Datetime.now(),
                }
            )
        return self.action_view_bill() if len(self) == 1 else True

    def action_reject(self):
        """Reject."""
        for invoice in self:
            if invoice.state == 'site_approved':
                group = 'construction_management.group_construction_manager'
            elif invoice.state == 'mgmt_approved':
                group = 'construction_management.group_construction_finance'
            else:
                raise UserError(_('Invoice %s cannot be rejected at this stage.', invoice.name))
            if not self.env.user.has_group(group):
                raise UserError(
                    _('You are not allowed to reject invoice %s at this stage.', invoice.name)
                )
            invoice.message_post(
                body=_(
                    'Invoice rejected by %(user)s. Reason: %(reason)s',
                    user=self.env.user.name,
                    reason=invoice.rejection_reason or '-',
                )
            )
        self.write({'state': 'rejected'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        for invoice in self:
            if invoice.state not in ('rejected', 'cancelled'):
                raise UserError(_('Only rejected or cancelled invoices can be reset to draft.'))
        self.write(
            {
                'state': 'draft',
                'site_approved_by_id': False,
                'site_approved_date': False,
                'mgmt_approved_by_id': False,
                'mgmt_approved_date': False,
            }
        )
        self._refresh_previous()
        return True

    def action_cancel(self):
        """Cancel."""
        for invoice in self:
            if invoice.state == 'finance_approved':
                raise UserError(
                    _(
                        'Audited invoices cannot be cancelled. Cancel the vendor bill from'
                        ' Accounting.'
                    )
                )
        self.write({'state': 'cancelled'})
        return True

    def _prepare_bill_vals(self):
        self.ensure_one()
        project = self.project_id
        distribution = model_attribute(project, '_get_analytic_distribution')()
        expense_account = model_attribute(project, '_get_company_account')(
            'construction_sub_expense_account_id'
        )
        lines = []
        for line in self.line_ids.filtered(lambda l: l.current_quantity > 0):
            lines.append(
                Command.create(
                    {
                        'name': (
                            line.contract_line_id.name
                            or line.contract_line_id.boq_item_id.display_name
                        ),
                        'quantity': line.current_quantity,
                        'price_unit': line.unit_price,
                        'account_id': expense_account.id,
                        'analytic_distribution': distribution,
                        'construction_boq_item_id': line.contract_line_id.boq_item_id.id,
                        'construction_boq_component_id': line.contract_line_id.boq_component_id.id,
                        'construction_cost_type': 'subcontract',
                        **(
                            {
                                'tax_ids': [
                                    Command.set(project.company_id.construction_sub_tax_ids.ids)
                                ]
                            }
                            if project.company_id.construction_sub_tax_ids
                            else {}
                        ),
                    }
                )
            )
        if not float_is_zero(self.guarantee_amount, precision_rounding=self.currency_id.rounding):
            name = _('Work guarantee (%s%%)', self.contract_id.guarantee_percent)
            guarantee_account = adjustment_account(
                project, 'construction_sub_retention_account_id', _('Work guarantee')
            )
            lines.append(
                adjustment_line(name, self.guarantee_amount, guarantee_account, distribution)
            )
        if not float_is_zero(
            self.advance_deduction_amount, precision_rounding=self.currency_id.rounding
        ):
            lines.append(
                adjustment_line(
                    _('Advance recovery (%s%%)', self.contract_id.advance_deduction_percent),
                    self.advance_deduction_amount,
                    adjustment_account(
                        project, 'construction_sub_advance_account_id', _('Advance recovery')
                    ),
                    distribution,
                )
            )
        append_invoice_deductions(lines, self, project, distribution)
        return {
            'move_type': 'in_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': self.date,
            'ref': self.vendor_reference or self.name,
            'invoice_origin': f'{self.contract_id.name} / {self.name}',
            'company_id': self.company_id.id,
            'construction_project_id': project.id,
            'construction_subcontract_invoice_id': self.id,
            'invoice_line_ids': lines,
        }

    def action_view_bill(self):
        """View bill."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('No vendor bill has been created yet.'))
        return journal_entry_action(self.move_id)
