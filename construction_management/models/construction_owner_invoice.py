"""Construction owner invoice for construction management."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from .construction_common import (
    append_invoice_deductions,
    project_field,
    reference_field,
    workflow_status_field,
)
from .invoice_adjustments import adjustment_account, adjustment_line
from .runtime import model_attribute

PRICE_INCREASE_THRESHOLD = 25.0
OPEN_STATES = ('to_approve', 'to_approve_exceptional', 'approved', 'invoiced')


class ConstructionOwnerInvoice(models.Model):
    """Construction owner invoice."""

    _name = 'construction.owner.invoice'
    _description = 'Owner Invoice (Progress Certificate)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = reference_field()
    project_id = project_field(domain="[('state', 'in', ('running', 'suspended', 'preliminary'))]")
    partner_id = fields.Many2one(related='project_id.partner_id', string='Customer', store=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    date = fields.Date(
        string='Invoice Date', required=True, default=fields.Date.context_today, tracking=True
    )
    invoice_type = fields.Selection(
        [
            ('advance', 'Advance Payment Invoice'),
            ('progress', 'Progress Invoice'),
        ],
        string='Invoice Type',
        compute='_compute_invoice_type',
        store=True,
        readonly=False,
        required=True,
        precompute=True,
        tracking=True,
        help=(
            "Advance Payment Invoice: invoices the advance payment of the contract to the owner"
            " (first invoice).\nProgress Invoice: invoices the executed quantities, less the"
            " contractual deductions."
        ),
    )
    advance_amount = fields.Monetary(
        string='Advance Payment',
        compute='_compute_advance_amount',
        store=True,
        readonly=False,
        precompute=True,
        help=(
            "Advance payment invoiced to the owner: the advance of the customer contract not"
            " received or invoiced yet."
        ),
    )
    period_start = fields.Date(string='Period From')
    period_end = fields.Date(string='Period To')
    note = fields.Text(string='Notes')
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('to_approve', 'Waiting Senior Management'),
            ('to_approve_exceptional', 'Waiting Exceptional Approval'),
            ('approved', 'Approved'),
            ('invoiced', 'Invoiced'),
            ('cancelled', 'Cancelled'),
        ]
    )

    line_ids = fields.One2many(
        'construction.owner.invoice.line', 'invoice_id', string='Lines', copy=True
    )
    deduction_ids = fields.One2many(
        'construction.owner.invoice.deduction', 'invoice_id', string='Deductions'
    )

    max_price_increase = fields.Float(
        compute='_compute_price_increase', store=True, string='Max Price Increase (%)'
    )
    approval_level = fields.Selection(
        [
            ('none', 'Not Required'),
            ('senior', 'Senior Management'),
            ('exceptional', 'Exceptional Approval'),
        ],
        compute='_compute_price_increase',
        store=True,
        string='Required Approval',
    )
    senior_approved_by_id = fields.Many2one(
        'res.users', string='Approved by (Senior Mgmt)', readonly=True, copy=False
    )
    senior_approved_date = fields.Datetime(string='Senior Approval Date', readonly=True, copy=False)
    exceptional_approved_by_id = fields.Many2one(
        'res.users', string='Approved by (Exceptional)', readonly=True, copy=False
    )
    exceptional_approved_date = fields.Datetime(
        string='Exceptional Approval Date', readonly=True, copy=False
    )
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)

    previous_amount = fields.Monetary(compute='_compute_gross', store=True, string='Previous Works')
    gross_amount = fields.Monetary(compute='_compute_gross', store=True, string='Current Works')
    cumulative_amount = fields.Monetary(
        compute='_compute_gross', store=True, string='Cumulative Works'
    )

    retention_percent = fields.Float(
        string='Work Guarantee (%)',
        compute='_compute_contract_rates',
        store=True,
        readonly=False,
        precompute=True,
    )
    retention_amount = fields.Monetary(
        compute='_compute_amounts', store=True, string='Work Guarantee'
    )
    advance_deduction_percent = fields.Float(
        string='Advance Deduction (%)',
        compute='_compute_contract_rates',
        store=True,
        readonly=False,
        precompute=True,
    )
    advance_deduction_amount = fields.Monetary(
        compute='_compute_amounts', store=True, string='Advance Deduction'
    )
    insurance_percent = fields.Float(
        string='Final Insurance (%)',
        compute='_compute_contract_rates',
        store=True,
        readonly=False,
        precompute=True,
        help=(
            "Final insurance withheld by the owner on this invoice, up to the final insurance of"
            " the contract not yet paid or withheld."
        ),
    )
    insurance_amount = fields.Monetary(
        compute='_compute_amounts', store=True, string='Final Insurance'
    )
    available_advance = fields.Monetary(compute='_compute_balances', string='Advance to Recover')
    remaining_insurance = fields.Monetary(
        compute='_compute_balances', string='Final Insurance to Withhold'
    )
    deduction_total = fields.Monetary(
        compute='_compute_amounts', store=True, string='Variable Deductions'
    )
    net_amount = fields.Monetary(compute='_compute_amounts', store=True, string='Net Amount')

    move_id = fields.Many2one('account.move', string='Customer Invoice', readonly=True, copy=False)
    move_state = fields.Selection(related='move_id.state', string='Invoice Status')
    payment_state = fields.Selection(related='move_id.payment_state', string='Payment Status')

    @api.depends('line_ids.price_increase_percent', 'line_ids.current_quantity')
    def _compute_price_increase(self):
        for invoice in self:
            lines = invoice.line_ids.filtered(lambda line: line.current_quantity > 0)
            increase = max(lines.mapped('price_increase_percent') or [0.0])
            invoice.max_price_increase = increase
            if float_compare(increase, 0.0, precision_digits=4) <= 0:
                invoice.approval_level = 'none'
            elif float_compare(increase, PRICE_INCREASE_THRESHOLD, precision_digits=4) <= 0:
                invoice.approval_level = 'senior'
            else:
                invoice.approval_level = 'exceptional'

    @api.depends('line_ids.amount_current', 'line_ids.previous_amount')
    def _compute_gross(self):
        for invoice in self:
            invoice.gross_amount = sum(invoice.line_ids.mapped('amount_current'))
            invoice.previous_amount = sum(invoice.line_ids.mapped('previous_amount'))
            invoice.cumulative_amount = invoice.previous_amount + invoice.gross_amount

    @api.depends('project_id')
    def _compute_invoice_type(self):
        """The first invoice of a contract with an advance payment is the advance payment
        invoice."""
        for invoice in self:
            if invoice.state != 'draft' or invoice.line_ids:

                invoice.invoice_type = invoice.invoice_type or 'progress'
                continue
            project = invoice.project_id
            currency = project.currency_id or self.env.company.currency_id
            invoice.invoice_type = (
                'advance'
                if project
                and project.advance_payment_amount
                and currency.compare_amounts(
                    model_attribute(invoice, '_get_advance_to_invoice')(), 0.0
                )
                > 0
                else 'progress'
            )

    @api.depends('project_id', 'invoice_type')
    def _compute_advance_amount(self):
        for invoice in self:
            if invoice.state != 'draft':
                invoice.advance_amount = invoice.advance_amount
            elif invoice.invoice_type == 'advance':
                invoice.advance_amount = max(
                    model_attribute(invoice, '_get_advance_to_invoice')(), 0.0
                )
            else:
                invoice.advance_amount = 0.0

    @api.depends('project_id', 'invoice_type')
    def _compute_contract_rates(self):
        for invoice in self:
            if invoice.state != 'draft':

                invoice.retention_percent = invoice.retention_percent
                invoice.advance_deduction_percent = invoice.advance_deduction_percent
                invoice.insurance_percent = invoice.insurance_percent
                continue
            project = invoice.project_id
            progress = invoice.invoice_type == 'progress'
            invoice.retention_percent = project.guarantee_percent if progress else 0.0
            invoice.advance_deduction_percent = (
                project.advance_deduction_percent if progress else 0.0
            )
            invoice.insurance_percent = project.final_insurance_percent if progress else 0.0

    @api.depends('project_id', 'invoice_type', 'state')
    def _compute_balances(self):
        for invoice in self:
            invoice.available_advance = max(
                model_attribute(invoice, '_get_available_advance')(), 0.0
            )
            invoice.remaining_insurance = max(
                model_attribute(invoice, '_get_remaining_insurance')(), 0.0
            )

    @api.depends(
        'gross_amount',
        'retention_percent',
        'advance_deduction_percent',
        'insurance_percent',
        'deduction_ids.amount',
        'invoice_type',
        'advance_amount',
    )
    def _compute_amounts(self):
        for invoice in self:
            currency = invoice.currency_id or self.env.company.currency_id
            if invoice.invoice_type == 'advance':
                invoice.retention_amount = invoice.advance_deduction_amount = (
                    invoice.insurance_amount
                ) = 0.0
                invoice.deduction_total = 0.0
                invoice.net_amount = invoice.advance_amount
                continue
            gross = invoice.gross_amount
            invoice.retention_amount = currency.round(gross * invoice.retention_percent / 100.0)
            advance = currency.round(gross * invoice.advance_deduction_percent / 100.0)
            invoice.advance_deduction_amount = min(
                advance, max(model_attribute(invoice, '_get_available_advance')(), 0.0)
            )
            insurance = currency.round(gross * invoice.insurance_percent / 100.0)
            invoice.insurance_amount = min(
                insurance, max(model_attribute(invoice, '_get_remaining_insurance')(), 0.0)
            )
            invoice.deduction_total = sum(invoice.deduction_ids.mapped('amount'))
            invoice.net_amount = (
                gross
                - invoice.retention_amount
                - invoice.advance_deduction_amount
                - invoice.insurance_amount
                - invoice.deduction_total
            )

    def _other_open_invoices(self):
        self.ensure_one()
        return self.project_id.owner_invoice_ids.filtered(
            lambda inv: inv.state in OPEN_STATES and inv.id != self._origin.id
        )

    def _get_available_advance(self):
        """Advance received (receipts) or invoiced to the owner, not yet recovered by other owner
        invoices."""
        self.ensure_one()
        project = self.project_id
        if not project:
            return 0.0
        received = sum(
            project.operation_ids.filtered(
                lambda op: op.state == 'posted' and op.operation_type == 'advance_received'
            ).mapped('amount')
        )
        others = self._other_open_invoices()
        invoiced = sum(
            others.filtered(lambda inv: inv.invoice_type == 'advance').mapped('advance_amount')
        )
        return received + invoiced - sum(others.mapped('advance_deduction_amount'))

    def _get_advance_to_invoice(self):
        """Advance payment of the contract not yet received nor invoiced to the owner."""
        self.ensure_one()
        project = self.project_id
        if not project:
            return 0.0
        received = sum(
            project.operation_ids.filtered(
                lambda op: op.state == 'posted' and op.operation_type == 'advance_received'
            ).mapped('amount')
        )

        others = project.owner_invoice_ids.filtered(
            lambda inv: inv.state != 'cancelled'
            and inv.id != self._origin.id
            and inv.invoice_type == 'advance'
        )
        invoiced = sum(others.mapped('advance_amount'))
        return project.advance_payment_amount - received - invoiced

    def _get_remaining_insurance(self):
        """Final insurance of the contract not yet paid (receipts) nor withheld by other owner
        invoices."""
        self.ensure_one()
        project = self.project_id
        if not project:
            return 0.0
        paid = sum(
            project.operation_ids.filtered(
                lambda op: op.state == 'posted' and op.operation_type == 'insurance_payment'
            ).mapped('amount')
        )
        withheld = sum(self._other_open_invoices().mapped('insurance_amount'))
        return project.final_insurance_amount - paid - withheld

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.owner.invoice'
                ) or _('New')
        invoices = super().create(vals_list)
        model_attribute(invoices, '_refresh_line_quantities')()

        invoices.filtered(
            lambda inv: inv.state == 'draft' and inv.invoice_type == 'progress' and not inv.line_ids
        ).action_generate_lines()
        return invoices

    def write(self, vals):
        """Write."""
        if 'project_id' in vals:
            for invoice in self:
                if invoice.line_ids and invoice.project_id.id != vals['project_id']:
                    raise UserError(
                        _('You cannot change the project of an invoice that has lines.')
                    )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_owner_invoice(self):
        for invoice in self:
            if invoice.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled owner invoices can be deleted.'))

    def _refresh_line_quantities(self):
        line_model = self.env['construction.owner.invoice.line']
        for invoice in self.filtered(lambda inv: inv.state == 'draft'):
            for line in invoice.line_ids:
                previous_lines = line_model.search(
                    [
                        ('boq_item_id', '=', line.boq_item_id.id),
                        ('invoice_id', '!=', invoice.id),
                        ('invoice_id.project_id', '=', invoice.project_id.id),
                        ('invoice_state', 'in', OPEN_STATES),
                    ]
                )
                line.write(
                    {
                        'boq_quantity': line.boq_item_id.total_quantity,
                        'contract_price': line.boq_item_id.unit_price,
                        'previous_quantity': sum(previous_lines.mapped('current_quantity')),
                        'previous_amount': sum(previous_lines.mapped('amount_current')),
                    }
                )
            self.env.add_to_compute(self._fields['net_amount'], invoice)

    def action_generate_lines(self):
        """Generate lines."""
        for invoice in self:
            if invoice.state != 'draft':
                raise UserError(_('Lines can only be generated on draft invoices.'))
            if invoice.invoice_type == 'advance':
                continue
            existing = invoice.line_ids.boq_item_id
            vals_list = []
            for item in invoice.project_id.boq_item_ids:
                if item in existing:
                    continue
                vals_list.append(
                    {
                        'invoice_id': invoice.id,
                        'boq_item_id': item.id,
                        'sequence': item.sequence,
                        'unit_price': item.unit_price,
                        'current_quantity': 0.0,
                    }
                )
            if vals_list:
                self.env['construction.owner.invoice.line'].create(vals_list)
            model_attribute(invoice, '_refresh_line_quantities')()
            invoice.action_compute_deductions()
        return True

    def action_refresh(self):
        """Refresh."""
        self._refresh_line_quantities()
        self.action_compute_deductions()
        return True

    def _get_applicable_deductions(self):
        """Customer deductions of the project policy that apply to this invoice: 'once' deductions
        only while no other (non cancelled) owner invoice of the project already carries them.
        """
        self.ensure_one()
        policy = self.project_id.deduction_ids.filtered(
            lambda d: d.active and d.applies_to == 'owner'
        )
        return policy.filtered(
            lambda d: d.frequency == 'every'
            or not model_attribute(d, '_applied_on_other_invoice')(self)
        )

    def action_compute_deductions(self):
        """Recompute the deductions coming from the project policy (manual lines are kept)."""
        for invoice in self:
            if invoice.state != 'draft':
                raise UserError(_('Deductions can only be recomputed on draft invoices.'))
            invoice.deduction_ids.filtered('project_deduction_id').unlink()
            if invoice.invoice_type == 'advance':
                continue
            vals_list = [
                {
                    'invoice_id': invoice.id,
                    'project_deduction_id': deduction.id,
                    'name': deduction.name,
                    'account_id': deduction.account_id.id,
                }
                for deduction in model_attribute(invoice, '_get_applicable_deductions')()
            ]
            if vals_list:
                self.env['construction.owner.invoice.deduction'].create(vals_list)
        return True

    def _check_once_deductions(self):
        for invoice in self:
            for line in invoice.deduction_ids.filtered(
                lambda d: d.project_deduction_id.frequency == 'once' and d.amount > 0
            ):
                if model_attribute(line.project_deduction_id, '_applied_on_other_invoice')(invoice):
                    raise UserError(
                        _(
                            'Deduction "%(name)s" is applied only once and is already on another'
                            ' owner invoice. Recompute the deductions of %(invoice)s.',
                            name=line.name,
                            invoice=invoice.name,
                        )
                    )

    def _check_quantities(self):
        for invoice in self:
            lines = invoice.line_ids.filtered(lambda line: line.current_quantity > 0)
            if not lines:
                raise UserError(
                    _('Owner invoice %s has no current quantity to invoice.', invoice.name)
                )
            for line in invoice.line_ids:
                if line.current_quantity < 0:
                    raise ValidationError(
                        _(
                            'Current quantity of %s cannot be negative.',
                            line.boq_item_id.display_name,
                        )
                    )
                rounding = line.boq_item_id.uom_id.rounding or 0.0001
                if (
                    float_compare(
                        line.previous_quantity + line.current_quantity,
                        line.boq_quantity,
                        precision_rounding=rounding,
                    )
                    > 0
                ):
                    raise ValidationError(
                        _(
                            'The cumulative quantity of %(item)s (%(qty)s) exceeds the approved BOQ'
                            ' quantity (%(boq)s). Please issue a change order first.',
                            item=line.boq_item_id.display_name,
                            qty=line.previous_quantity + line.current_quantity,
                            boq=line.boq_quantity,
                        )
                    )
                if line.unit_price < 0:
                    raise ValidationError(
                        _('Unit price of %s cannot be negative.', line.boq_item_id.display_name)
                    )

    def _check_advance_invoice(self):
        for invoice in self:
            rounding = invoice.currency_id.rounding
            if float_compare(invoice.advance_amount, 0.0, precision_rounding=rounding) <= 0:
                raise UserError(_('Set the advance payment to invoice on %s.', invoice.name))
            agreed = invoice.project_id.advance_payment_amount
            if (
                agreed
                and float_compare(
                    invoice.advance_amount,
                    model_attribute(invoice, '_get_advance_to_invoice')(),
                    precision_rounding=rounding,
                )
                > 0
            ):
                raise UserError(
                    _(
                        'The advance payment invoiced (%(amount)s) exceeds the advance of the'
                        ' customer contract not yet received or invoiced (%(left)s).',
                        amount=invoice.advance_amount,
                        left=max(model_attribute(invoice, '_get_advance_to_invoice')(), 0.0),
                    )
                )

    def action_submit(self):
        """Submit."""
        for invoice in self:
            if invoice.state != 'draft':
                raise UserError(_('Only draft owner invoices can be submitted.'))
            if invoice.invoice_type == 'advance':
                model_attribute(invoice, '_check_advance_invoice')()
                invoice.write({'state': 'approved', 'submitted_by_id': self.env.user.id})
                continue
            model_attribute(invoice, '_refresh_line_quantities')()
            model_attribute(invoice, '_check_quantities')()
            model_attribute(invoice, '_check_once_deductions')()
            if invoice.approval_level == 'none':
                new_state = 'approved'
            elif invoice.approval_level == 'senior':
                new_state = 'to_approve'
            else:
                new_state = 'to_approve_exceptional'
            invoice.write({'state': new_state, 'submitted_by_id': self.env.user.id})
            if new_state == 'to_approve':
                invoice.message_post(
                    body=_(
                        'Price increase of %s%% requires Senior Management approval.',
                        round(invoice.max_price_increase, 2),
                    )
                )
            elif new_state == 'to_approve_exceptional':
                invoice.message_post(
                    body=_(
                        'Price increase of %s%% exceeds 25%% and requires exceptional approval.',
                        round(invoice.max_price_increase, 2),
                    )
                )
        return True

    def action_approve_senior(self):
        """Approve senior."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can approve this invoice.'))
        for invoice in self:
            if invoice.state != 'to_approve':
                raise UserError(
                    _('Invoice %s is not waiting for Senior Management approval.', invoice.name)
                )
        self.write(
            {
                'state': 'approved',
                'senior_approved_by_id': self.env.user.id,
                'senior_approved_date': fields.Datetime.now(),
            }
        )
        return True

    def action_approve_exceptional(self):
        """Approve exceptional."""
        if not self.env.user.has_group('construction_management.group_construction_executive'):
            raise UserError(_('Only Executive Management can grant exceptional approval.'))
        for invoice in self:
            if invoice.state != 'to_approve_exceptional':
                raise UserError(
                    _('Invoice %s is not waiting for exceptional approval.', invoice.name)
                )
        self.write(
            {
                'state': 'approved',
                'exceptional_approved_by_id': self.env.user.id,
                'exceptional_approved_date': fields.Datetime.now(),
            }
        )
        return True

    def action_reject(self):
        """Reject."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can reject owner invoices.'))
        for invoice in self:
            if invoice.state not in ('to_approve', 'to_approve_exceptional', 'approved'):
                raise UserError(_('Only invoices waiting for approval can be rejected.'))
            invoice.message_post(
                body=_('Invoice rejected by %s and returned to draft.', self.env.user.name)
            )
        self.write({'state': 'draft'})
        return True

    def _prepare_move_vals(self):
        self.ensure_one()
        project = self.project_id
        company = project.company_id
        distribution = model_attribute(project, '_get_analytic_distribution')()
        revenue_account = company.construction_revenue_account_id
        lines = []
        if self.invoice_type == 'advance':

            vals = {
                'name': _(
                    'Advance payment (%(percent)s%%) - %(project)s',
                    percent=project.advance_payment_percent,
                    project=project.display_name,
                ),
                'quantity': 1.0,
                'price_unit': self.advance_amount,
                'account_id': (
                    model_attribute(project, '_check_invoice_line_account')(
                        model_attribute(project, '_get_company_account')(
                            'construction_advance_account_id'
                        ),
                        _('Advance payment'),
                    ).id
                ),
                'tax_ids': [Command.set(company.construction_owner_tax_ids.ids)],
                'analytic_distribution': distribution,
            }
            lines.append(Command.create(vals))
        for line in self.line_ids.filtered(
            lambda l: l.current_quantity > 0 and self.invoice_type == 'progress'
        ):
            vals = {
                'name': (
                    f"{line.boq_item_id.display_name!s}\n{line.boq_item_id.description or ''!s}"
                ),
                'quantity': line.current_quantity,
                'price_unit': line.unit_price,
                'analytic_distribution': distribution,
                'construction_boq_item_id': line.boq_item_id.id,
            }
            if revenue_account:
                vals['account_id'] = revenue_account.id
            if company.construction_owner_tax_ids:
                vals['tax_ids'] = [Command.set(company.construction_owner_tax_ids.ids)]
            lines.append(Command.create(vals))
        if not float_is_zero(self.retention_amount, precision_rounding=self.currency_id.rounding):
            name = _('Work guarantee (%s%%)', self.retention_percent)
            retention_account = adjustment_account(
                project, 'construction_retention_account_id', _('Work guarantee')
            )
            lines.append(
                adjustment_line(name, self.retention_amount, retention_account, distribution)
            )
        if not float_is_zero(
            self.advance_deduction_amount, precision_rounding=self.currency_id.rounding
        ):
            lines.append(
                adjustment_line(
                    _('Advance payment deduction (%s%%)', self.advance_deduction_percent),
                    self.advance_deduction_amount,
                    adjustment_account(
                        project, 'construction_advance_account_id', _('Advance payment')
                    ),
                    distribution,
                    Command.set(self._get_advance_taxes().ids),
                )
            )
        if not float_is_zero(self.insurance_amount, precision_rounding=self.currency_id.rounding):
            lines.append(
                adjustment_line(
                    _('Final insurance (%s%%)', self.insurance_percent),
                    self.insurance_amount,
                    adjustment_account(
                        project, 'construction_insurance_account_id', _('Final insurance')
                    ),
                    distribution,
                )
            )
        append_invoice_deductions(lines, self, project, distribution)
        return {
            'move_type': 'out_invoice',
            'partner_id': project.partner_id.id,
            'invoice_date': self.date,
            'invoice_origin': f'{project.code} / {self.name}',
            'ref': self.name,
            'company_id': company.id,
            'construction_project_id': project.id,
            'construction_owner_invoice_id': self.id,
            'invoice_line_ids': lines,
        }

    def _get_advance_taxes(self):
        """Taxes of the advance payment invoices of the project (none when the advance was only
        received)."""
        self.ensure_one()
        advance_invoices = self.project_id.owner_invoice_ids.filtered(
            lambda inv: inv.invoice_type == 'advance' and inv.state == 'invoiced' and inv.move_id
        )
        return advance_invoices.sudo().move_id.invoice_line_ids.tax_ids

    def action_create_invoice(self):
        """Create invoice."""
        if not (
            self.env.user.has_group('construction_management.group_construction_finance')
            or self.env.user.has_group('construction_management.group_construction_manager')
        ):
            raise UserError(_('Only Finance or Senior Management can confirm owner invoices.'))
        for invoice in self:
            if invoice.state != 'approved':
                raise UserError(_('Invoice %s must be approved before confirmation.', invoice.name))
            if invoice.invoice_type == 'advance':
                model_attribute(invoice, '_check_advance_invoice')()
            else:
                model_attribute(invoice, '_check_quantities')()
            for deduction in invoice.deduction_ids:
                if not deduction.account_id:
                    raise UserError(_('Please set an account on deduction %s.', deduction.name))
            move = (
                self.env['account.move']
                .sudo()
                .with_company(invoice.company_id)
                .create(model_attribute(invoice, '_prepare_move_vals')())
            )
            invoice.write({'move_id': move.id, 'state': 'invoiced'})
        return self.action_view_move() if len(self) == 1 else True

    def action_cancel(self):
        """Cancel."""
        for invoice in self:
            if invoice.move_id and invoice.sudo().move_id.state == 'posted':
                raise UserError(
                    _(
                        'The customer invoice of %s is posted. Reset it to draft or reverse it'
                        ' first.',
                        invoice.name,
                    )
                )
            if invoice.move_id and invoice.sudo().move_id.state == 'draft':
                invoice.move_id.sudo().button_cancel()
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        for invoice in self:
            if invoice.state != 'cancelled':
                raise UserError(_('Only cancelled invoices can be reset to draft.'))
        self.write(
            {
                'state': 'draft',
                'move_id': False,
                'senior_approved_by_id': False,
                'senior_approved_date': False,
                'exceptional_approved_by_id': False,
                'exceptional_approved_date': False,
            }
        )
        self._refresh_line_quantities()
        return True

    def action_view_move(self):
        """View move."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('No customer invoice has been created yet.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }
