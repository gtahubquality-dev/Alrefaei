"""Construction subcontract for construction management."""

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import formatLang, float_compare, float_is_zero

from .runtime import model_attribute

from .construction_common import project_field, requester_field, workflow_status_field


class ConstructionSubcontract(models.Model):
    """Construction subcontract."""

    _name = 'construction.subcontract'
    _description = 'Subcontractor Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(
        string='Contract Serial Number',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    project_id = project_field()
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    partner_id = fields.Many2one(
        'res.partner', string='Subcontractor', required=True, tracking=True
    )
    date_start = fields.Date(string='Start Date', default=fields.Date.context_today, tracking=True)
    duration_months = fields.Integer(string='Contract Duration (Months)', tracking=True)
    date_end = fields.Date(string='End Date', compute='_compute_date_end', store=True)
    guarantee_percent = fields.Float(string='Work Guarantee (%)', tracking=True)
    advance_amount = fields.Monetary(string='Advance Payment', tracking=True)
    advance_deduction_percent = fields.Float(
        string='Advance Deduction (%)',
        help="Percentage of each subcontractor invoice deducted to recover the advance.",
    )
    advance_journal_id = fields.Many2one(
        'account.journal',
        string='Advance Payment Journal',
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
    )
    advance_move_id = fields.Many2one(
        'account.move', string='Advance Entry', readonly=True, copy=False
    )
    advance_payment_move_id = fields.Many2one(
        'account.move', string='Advance Payment Entry', readonly=True, copy=False
    )
    requested_by_id = requester_field()
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    state = workflow_status_field(
        [
            ('draft', 'Request'),
            ('to_approve', 'Waiting Management'),
            ('active', 'Active'),
            ('closed', 'Closed'),
            ('cancelled', 'Cancelled'),
        ]
    )
    line_ids = fields.One2many(
        'construction.subcontract.line', 'contract_id', string='Assigned BOQ Items', copy=True
    )
    exceeds_boq = fields.Boolean(
        string='Exceeds BOQ',
        readonly=True,
        copy=False,
        help="Assigned quantities exceed the BOQ: Senior Management approval required.",
    )
    boq_exceed_note = fields.Text(string='BOQ Excess', readonly=True, copy=False)
    has_boq_excess = fields.Boolean(
        compute='_compute_has_boq_excess',
        string='Lines Exceed BOQ',
        help="Some lines exceed the BOQ quantity still available or the BOQ subcontract unit cost.",
    )
    invoice_ids = fields.One2many(
        'construction.subcontract.invoice', 'contract_id', string='Invoices'
    )
    terms = fields.Html(string='Terms & Conditions')
    deduction_ids = fields.One2many(
        'construction.subcontract.deduction',
        'contract_id',
        string='Variable Deductions & Suspense Amounts',
        copy=True,
    )
    amendment_ids = fields.One2many(
        'construction.subcontract.amendment', 'contract_id', string='Amendments'
    )
    amendment_count = fields.Integer(compute='_compute_amendment_count', string='Amendments Count')
    guarantee_ids = fields.One2many(
        'construction.guarantee', 'subcontract_id', string='Guarantees Received'
    )
    operation_ids = fields.One2many(
        'construction.project.operation', 'subcontract_id', string='Refunds'
    )
    guarantee_refunded = fields.Monetary(compute='_compute_invoiced', string='Guarantee Refunded')
    guarantee_balance = fields.Monetary(compute='_compute_invoiced', string='Guarantee Balance')
    deductions_total = fields.Monetary(compute='_compute_invoiced', string='Variable Deductions')

    amount_total = fields.Monetary(compute='_compute_amounts', store=True, string='Contract Value')
    invoiced_amount = fields.Monetary(compute='_compute_invoiced', string='Invoiced')
    guarantee_held = fields.Monetary(compute='_compute_invoiced', string='Guarantee Held')
    advance_deducted = fields.Monetary(compute='_compute_invoiced', string='Advance Recovered')
    advance_balance = fields.Monetary(compute='_compute_invoiced', string='Advance Remaining')
    invoice_count = fields.Integer(compute='_compute_invoiced', string='Invoices Count')

    @api.depends('date_start', 'duration_months')
    def _compute_date_end(self):
        for contract in self:
            if contract.date_start and contract.duration_months > 0:
                contract.date_end = contract.date_start + relativedelta(
                    months=contract.duration_months, days=-1
                )
            else:
                contract.date_end = False

    @api.depends('line_ids.amount')
    def _compute_amounts(self):
        for contract in self:
            contract.amount_total = sum(contract.line_ids.mapped('amount'))

    @api.depends('line_ids.exceeds_quantity', 'line_ids.exceeds_price')
    def _compute_has_boq_excess(self):
        for contract in self:
            contract.has_boq_excess = any(
                line.exceeds_quantity or line.exceeds_price for line in contract.line_ids
            )

    def _compute_amendment_count(self):
        for contract in self:
            contract.amendment_count = len(contract.amendment_ids)

    def _compute_invoiced(self):
        for contract in self:
            done = contract.invoice_ids.filtered(lambda inv: inv.state == 'finance_approved')
            contract.invoiced_amount = sum(done.mapped('gross_amount'))
            contract.guarantee_held = sum(done.mapped('guarantee_amount'))
            contract.advance_deducted = sum(done.mapped('advance_deduction_amount'))
            paid = contract.advance_amount if contract.advance_move_id else 0.0
            contract.advance_balance = paid - contract.advance_deducted
            contract.invoice_count = len(contract.invoice_ids)
            contract.deductions_total = sum(done.mapped('deduction_total'))
            refunds = contract.operation_ids.filtered(
                lambda op: op.state == 'posted' and op.operation_type == 'sub_retention_refund'
            )
            contract.guarantee_refunded = sum(refunds.mapped('amount'))
            contract.guarantee_balance = contract.guarantee_held - contract.guarantee_refunded

    @api.constrains(
        'guarantee_percent', 'advance_deduction_percent', 'advance_amount', 'duration_months'
    )
    def _check_values(self):
        for contract in self:
            if not 0.0 <= contract.guarantee_percent <= 100.0:
                raise ValidationError(_('The work guarantee percentage must be between 0 and 100.'))
            if not 0.0 <= contract.advance_deduction_percent <= 100.0:
                raise ValidationError(
                    _('The advance deduction percentage must be between 0 and 100.')
                )
            if contract.advance_amount < 0 or contract.duration_months < 0:
                raise ValidationError(_('Advance amount and duration cannot be negative.'))

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.subcontract'
                ) or _('New')
        contracts = super().create(vals_list)
        for contract, vals in zip(contracts, vals_list):
            if 'deduction_ids' not in vals:
                model_attribute(contract, '_load_project_deductions')()
        return contracts

    def _load_project_deductions(self):
        """Copy the subcontractor deduction policy of the project (lines not loaded yet)."""
        deduction_model = self.env['construction.subcontract.deduction']
        for contract in self:
            policy = contract.project_id.deduction_ids.filtered(
                lambda d: d.active and d.applies_to == 'subcontractor'
            )
            loaded = contract.with_context(active_test=False).deduction_ids.project_deduction_id
            vals_list = [
                dict(
                    model_attribute(line, '_subcontract_deduction_vals')(), contract_id=contract.id
                )
                for line in policy - loaded
            ]
            if vals_list:
                deduction_model.create(vals_list)

    def action_load_project_deductions(self):
        """Load project deductions."""
        for contract in self:
            if contract.state not in ('draft', 'to_approve'):
                raise UserError(_('The deduction policy can only be loaded on contract requests.'))
        self._load_project_deductions()
        return True

    def write(self, vals):
        """Write."""
        locked = {
            'guarantee_percent',
            'advance_deduction_percent',
            'advance_amount',
            'partner_id',
            'project_id',
        }
        if locked.intersection(vals):
            for contract in self:
                if contract.state not in ('draft', 'cancelled'):
                    raise UserError(
                        _(
                            'Financial terms of contract %s are locked after submission.',
                            contract.name,
                        )
                    )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_subcontract(self):
        for contract in self:
            if contract.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled contracts can be deleted.'))

    def _check_assigned_quantities(self):
        """Validate the assigned items and return the description of the quantities exceeding the
        BOQ (allowed only with the approval of Senior Management).
        """
        excess = []
        for contract in self:
            if not contract.line_ids:
                raise UserError(_('Please assign at least one BOQ item to the contract.'))
            assigned = {}
            for line in contract.line_ids:
                item = line.boq_item_id
                if item.project_id != contract.project_id:
                    raise ValidationError(
                        _('BOQ item %s does not belong to the contract project.', item.display_name)
                    )
                if float_compare(line.quantity, 0.0, precision_digits=6) <= 0:
                    raise ValidationError(
                        _('Assigned quantity of %s must be positive.', item.display_name)
                    )
                assigned[item] = assigned.get(item, 0.0) + line.quantity
            for item, quantity in assigned.items():
                other = item.subcontract_line_ids.filtered(
                    lambda line, current=contract: line.contract_id != current
                    and line.contract_state in ('to_approve', 'active', 'closed')
                )
                total = sum(other.mapped('quantity')) + quantity
                if float_compare(total, item.total_quantity, precision_digits=4) > 0:
                    excess.append(
                        _(
                            'Total subcontracted quantity of %(item)s (%(qty)s) exceeds its BOQ'
                            ' quantity (%(boq)s).',
                            item=item.display_name,
                            qty=total,
                            boq=item.total_quantity,
                        )
                    )
            for line in contract.line_ids.filtered('exceeds_price'):
                excess.append(
                    _(
                        'Unit price of %(item)s (%(price)s) exceeds its BOQ subcontract unit cost'
                        ' (%(cost)s).',
                        item=line.boq_item_id.display_name,
                        price=formatLang(
                            self.env, line.unit_price, currency_obj=contract.currency_id
                        ),
                        cost=formatLang(
                            self.env, line.boq_unit_cost, currency_obj=contract.currency_id
                        ),
                    )
                )
        return excess

    def action_submit(self):
        """Submit."""
        for contract in self:
            if contract.state != 'draft':
                raise UserError(_('Only contract requests can be submitted.'))
            for line in contract.line_ids.filtered(lambda l: not l.boq_component_id):
                works = line.boq_item_id.component_ids.filtered(
                    lambda c: c.component_type == 'subcontract'
                )
                if len(works) > 1:
                    raise UserError(
                        _(
                            'BOQ item %s has several subcontracted works: select the work covered'
                            ' by the line.',
                            line.boq_item_id.display_name,
                        )
                    )
            excess = model_attribute(contract, '_check_assigned_quantities')()
            contract.write(
                {
                    'state': 'to_approve',
                    'exceeds_boq': bool(excess),
                    'boq_exceed_note': '\n'.join(excess) or False,
                }
            )
            if excess:
                contract.message_post(
                    body=_(
                        'The assigned quantities exceed the BOQ, Senior Management approval is '
                        'required: %s',
                        ' '.join(excess),
                    )
                )
        return True

    def action_approve(self):
        """Approve."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can approve subcontractor contracts.'))
        for contract in self:
            if contract.state != 'to_approve':
                raise UserError(_('Only contracts waiting for management can be approved.'))
            excess = model_attribute(contract, '_check_assigned_quantities')()
            contract.write(
                {'exceeds_boq': bool(excess), 'boq_exceed_note': '\n'.join(excess) or False}
            )
            if excess:
                contract.message_post(
                    body=_(
                        'Quantities exceeding the BOQ approved by %(user)s: %(excess)s',
                        user=self.env.user.name,
                        excess=' '.join(excess),
                    )
                )
        self.write(
            {
                'state': 'active',
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            }
        )
        return True

    def action_reject(self):
        """Reject."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can reject subcontractor contracts.'))
        for contract in self:
            if contract.state != 'to_approve':
                raise UserError(_('Only contracts waiting for management can be rejected.'))
        self.write({'state': 'draft'})
        return True

    def action_close(self):
        """Close."""
        for contract in self:
            if contract.state != 'active':
                raise UserError(_('Only active contracts can be closed.'))
            if contract.invoice_ids.filtered(
                lambda inv: inv.state in ('draft', 'site_approved', 'mgmt_approved')
            ):
                raise UserError(
                    _('Please process pending invoices of contract %s first.', contract.name)
                )
        self.write({'state': 'closed'})
        self._refund_guarantee()
        return True

    def action_refund_guarantee(self):
        """Refund guarantee."""
        if not self.env.user.has_group('construction_management.group_construction_finance'):
            raise UserError(_('Only Finance can refund the subcontractor work guarantee.'))
        for contract in self:
            if contract.state not in ('active', 'closed'):
                raise UserError(
                    _('The work guarantee can only be refunded for active or closed contracts.')
                )
        return self._refund_guarantee()

    def _refund_guarantee(self):
        operation_model = self.env['construction.project.operation'].sudo()
        for contract in self:
            contract.invalidate_recordset(
                ['guarantee_held', 'guarantee_refunded', 'guarantee_balance']
            )
            amount = contract.guarantee_balance
            if (
                float_is_zero(amount, precision_rounding=contract.currency_id.rounding)
                or amount < 0
            ):
                continue
            operation = operation_model.create(
                {
                    'project_id': contract.project_id.id,
                    'subcontract_id': contract.id,
                    'operation_type': 'sub_retention_refund',
                    'amount': amount,
                    'name': _('Work guarantee refund - contract closing'),
                }
            )
            operation.action_post()
            contract.message_post(
                body=_('Work guarantee of %s refunded to the subcontractor.', amount)
            )
        return True

    def action_cancel(self):
        """Cancel."""
        for contract in self:
            if contract.invoice_ids.filtered(lambda inv: inv.state == 'finance_approved'):
                raise UserError(
                    _('Contract %s has approved invoices and cannot be cancelled.', contract.name)
                )
            if contract.advance_move_id:
                raise UserError(
                    _('Contract %s has a paid advance and cannot be cancelled.', contract.name)
                )
            pending = contract.invoice_ids.filtered(
                lambda inv: inv.state in ('site_approved', 'mgmt_approved')
            )
            if pending:
                raise UserError(
                    _(
                        'Contract %(contract)s has invoices in approval (%(invoices)s). Reject or'
                        ' cancel them first.',
                        contract=contract.name,
                        invoices=', '.join(pending.mapped('name')),
                    )
                )
            if contract.amendment_ids.filtered(lambda a: a.state == 'submitted'):
                raise UserError(
                    _('Contract %s has an amendment waiting for approval.', contract.name)
                )
            contract.invoice_ids.filtered(lambda inv: inv.state in ('draft', 'rejected')).write(
                {'state': 'cancelled'}
            )
        self.write({'state': 'cancelled'})
        return True

    def action_new_amendment(self):
        """New amendment."""
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_('Amendments can only be made on active contracts.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contract Amendment'),
            'res_model': 'construction.subcontract.amendment',
            'view_mode': 'form',
            'context': {'default_contract_id': self.id},
        }

    def action_view_amendments(self):
        """View amendments."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contract Amendments'),
            'res_model': 'construction.subcontract.amendment',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }

    def action_reset_draft(self):
        """Reset draft."""
        for contract in self:
            if contract.state != 'cancelled':
                raise UserError(_('Only cancelled contracts can be reset.'))
        self.write({'state': 'draft'})
        return True

    def action_pay_advance(self):
        """Pay advance."""
        if not (
            self.env.user.has_group('construction_management.group_construction_finance')
            or self.env.user.has_group('construction_management.group_construction_manager')
        ):
            raise UserError(_('Only Finance can register subcontractor advance payments.'))
        for contract in self:
            if contract.state != 'active':
                raise UserError(_('The advance can only be paid on active contracts.'))
            if contract.advance_move_id:
                raise UserError(
                    _('The advance of contract %s has already been registered.', contract.name)
                )
            if float_is_zero(
                contract.advance_amount, precision_rounding=contract.currency_id.rounding
            ):
                raise UserError(_('Contract %s has no advance amount.', contract.name))
            journal = contract.advance_journal_id
            if not journal or not journal.default_account_id:
                raise UserError(
                    _(
                        'Please select a bank or cash journal with a default account for the'
                        ' advance.'
                    )
                )
            project = contract.project_id
            partner = contract.partner_id.commercial_partner_id
            payable = partner.with_company(contract.company_id).property_account_payable_id
            if not payable:
                raise UserError(_('Subcontractor %s has no payable account.', partner.display_name))
            account = model_attribute(project, '_get_company_account')(
                'construction_sub_advance_account_id'
            )
            distribution = model_attribute(project, '_get_analytic_distribution')()
            label = _('Advance payment - %s', contract.name)
            move_model = self.env['account.move'].sudo().with_company(contract.company_id)
            today = fields.Date.context_today(self)

            move = move_model.create(
                {
                    'move_type': 'entry',
                    'journal_id': model_attribute(project, '_get_misc_journal')().id,
                    'date': today,
                    'ref': label,
                    'partner_id': partner.id,
                    'construction_project_id': project.id,
                    'line_ids': [
                        Command.create(
                            {
                                'name': label,
                                'account_id': account.id,
                                'partner_id': partner.id,
                                'debit': contract.advance_amount,
                                'credit': 0.0,
                                'analytic_distribution': distribution,
                            }
                        ),
                        Command.create(
                            {
                                'name': label,
                                'account_id': payable.id,
                                'partner_id': partner.id,
                                'debit': 0.0,
                                'credit': contract.advance_amount,
                            }
                        ),
                    ],
                }
            )
            move.action_post()

            payment = move_model.create(
                {
                    'move_type': 'entry',
                    'journal_id': journal.id,
                    'date': today,
                    'ref': label,
                    'partner_id': partner.id,
                    'construction_project_id': project.id,
                    'line_ids': [
                        Command.create(
                            {
                                'name': label,
                                'account_id': payable.id,
                                'partner_id': partner.id,
                                'debit': contract.advance_amount,
                                'credit': 0.0,
                            }
                        ),
                        Command.create(
                            {
                                'name': label,
                                'account_id': journal.default_account_id.id,
                                'partner_id': partner.id,
                                'debit': 0.0,
                                'credit': contract.advance_amount,
                            }
                        ),
                    ],
                }
            )
            payment.action_post()
            (move.line_ids | payment.line_ids).filtered(
                lambda line, account=payable: line.account_id == account and not line.reconciled
            ).reconcile()
            contract.write({'advance_move_id': move.id, 'advance_payment_move_id': payment.id})
        return True

    def action_create_invoice(self):
        """New progress invoice of the subcontractor, with all the contract items."""
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_('Invoices can only be created on approved (active) contracts.'))
        pending = self.invoice_ids.filtered(lambda inv: inv.state in ('draft', 'rejected'))
        if pending:
            raise UserError(
                _(
                    'Invoice %s is still in draft: complete or cancel it before creating a new'
                    ' one.',
                    pending[0].name,
                )
            )
        invoice = self.env['construction.subcontract.invoice'].create({'contract_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Subcontractor Invoice'),
            'res_model': 'construction.subcontract.invoice',
            'res_id': invoice.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    def action_view_invoices(self):
        """View invoices."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Subcontractor Invoices'),
            'res_model': 'construction.subcontract.invoice',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }
