"""Custody request for financial custody."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from .custody_common import create_custody_entry, custody_move_action, custody_status_field
from .runtime import model_attribute


class CustodyRequest(models.Model):
    """Custody request."""

    _name = 'custody.request'
    _description = 'Financial Custody'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New')
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    requested_by_id = fields.Many2one(
        'res.users', string='Requested By', default=lambda self: self.env.user, readonly=True
    )
    employee_id = fields.Many2one(
        'hr.employee.public',
        string='Employee',
        required=True,
        tracking=True,
        default=lambda record: model_attribute(record, '_default_employee')(),
        domain="[('company_id', 'in', (company_id, False))]",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Employee Contact',
        compute='_compute_partner_id',
        store=True,
        readonly=False,
        help="Partner used on the accounting entries of the custody.",
    )
    date = fields.Date(
        string='Request Date', required=True, default=fields.Date.context_today, tracking=True
    )
    purpose = fields.Text(string='Purpose', required=True)
    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    state = custody_status_field(
        [
            ('draft', 'Draft'),
            ('submitted', 'Waiting Review'),
            ('approved', 'Approved'),
            ('paid', 'Disbursed'),
            ('closed', 'Settled'),
            ('refused', 'Refused'),
            ('cancelled', 'Cancelled'),
        ],
    )
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    refuse_reason = fields.Text(string='Refusal Reason', copy=False)
    journal_id = fields.Many2one(
        'account.journal',
        string='Disbursement Journal',
        groups='financial_custody.group_custody_manager',
        default=lambda self: self.env.company.custody_journal_id,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    payment_date = fields.Date(string='Disbursement Date', copy=False)
    paid_by_id = fields.Many2one('res.users', string='Disbursed By', readonly=True, copy=False)
    move_id = fields.Many2one(
        'account.move',
        string='Disbursement Entry',
        readonly=True,
        copy=False,
        groups='financial_custody.group_custody_manager',
    )
    settlement_ids = fields.One2many('custody.settlement', 'custody_id', string='Settlements')
    settled_amount = fields.Monetary(compute='_compute_settlement', string='Settled Amount')
    balance = fields.Monetary(compute='_compute_settlement', string='Remaining Balance')
    settled_percent = fields.Float(compute='_compute_settlement', string='Settled (%)')
    settlement_count = fields.Integer(compute='_compute_settlement', string='Settlements Count')

    @api.model
    def _default_employee(self):
        employee = self.env.user.sudo().employee_id
        return self.env['hr.employee.public'].browse(employee.id) if employee else False

    @api.depends('employee_id')
    def _compute_partner_id(self):
        for custody in self:
            partner = custody.employee_id.work_contact_id
            if not partner and custody.employee_id.user_id:
                partner = custody.employee_id.user_id.partner_id
            custody.partner_id = partner

    def _compute_settlement(self):
        for custody in self:
            posted = custody.settlement_ids.filtered(lambda s: s.state == 'posted')
            settled = sum(posted.mapped('total_settled'))
            custody.settled_amount = settled
            custody.balance = (
                custody.amount - settled if custody.state in ('paid', 'closed') else custody.amount
            )
            custody.settled_percent = settled / custody.amount * 100.0 if custody.amount else 0.0
            custody.settlement_count = len(custody.settlement_ids)

    @api.constrains('amount')
    def _check_amount(self):
        for custody in self:
            if float_compare(custody.amount, 0.0, precision_digits=6) <= 0:
                raise ValidationError(_('The custody amount must be positive.'))

    def _is_custody_manager(self):
        return self.env.su or self.env.user.has_group('financial_custody.group_custody_manager')

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        is_manager = self._is_custody_manager()
        own_employees = self.env.user.sudo().employee_ids.ids
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('custody.request') or _('New')
            if not is_manager:

                vals.pop('partner_id', None)
                if vals.get('employee_id') and vals['employee_id'] not in own_employees:
                    raise UserError(_('You can only request a custody for yourself.'))
        return super().create(vals_list)

    def write(self, vals):
        """Write."""
        if 'partner_id' in vals and not self._is_custody_manager():
            for custody in self:
                if custody.partner_id.id != vals['partner_id']:
                    raise UserError(
                        _('Only the custody manager can change the employee contact of a custody.')
                    )
        if 'employee_id' in vals and not self._is_custody_manager():
            if vals['employee_id'] not in self.env.user.sudo().employee_ids.ids:
                raise UserError(_('You can only request a custody for yourself.'))
        if {'amount', 'employee_id'}.intersection(vals):
            for custody in self:
                if custody.state not in ('draft', 'refused'):
                    raise UserError(
                        _(
                            'The amount and employee of custody %s cannot be changed after'
                            ' submission.',
                            custody.name,
                        )
                    )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_custody_request(self):
        for custody in self:
            if custody.state not in ('draft', 'cancelled', 'refused'):
                raise UserError(_('Only draft, refused or cancelled custodies can be deleted.'))

    @api.depends('name', 'employee_id')
    def _compute_display_name(self):
        for custody in self:
            custody.display_name = (
                f'{custody.name} - {custody.employee_id.name}'
                if custody.employee_id
                else custody.name
            )

    def _check_previous_custodies(self):
        """Block new custody when the employee has an open custody below the threshold."""
        for custody in self:
            threshold = custody.company_id.custody_settlement_threshold
            open_custodies = self.sudo().search(
                [
                    ('employee_id', '=', custody.employee_id.id),
                    ('state', 'in', ('paid',)),
                    ('id', '!=', custody.id),
                ]
            )
            for previous in open_custodies:
                if float_compare(previous.settled_percent, threshold, precision_digits=2) < 0:
                    raise UserError(
                        _(
                            'You cannot request a new custody: custody %(ref)s is only %(pct)s%%'
                            ' settled. At least %(min)s%% of the previous custody must be settled'
                            ' first.',
                            ref=previous.name,
                            pct=round(previous.settled_percent, 2),
                            min=threshold,
                        )
                    )
            pending = self.sudo().search_count(
                [
                    ('employee_id', '=', custody.employee_id.id),
                    ('state', 'in', ('submitted', 'approved')),
                    ('id', '!=', custody.id),
                ]
            )
            if pending:
                raise UserError(
                    _(
                        'This employee already has a custody request waiting for review or'
                        ' disbursement.'
                    )
                )

    def action_submit(self):
        """Submit."""
        for custody in self:
            if custody.state not in ('draft', 'refused'):
                raise UserError(_('Only draft custodies can be submitted.'))
            model_attribute(custody, '_check_previous_custodies')()
        self.write({'state': 'submitted', 'refuse_reason': False})
        return True

    def _check_manager(self):
        if not self.env.user.has_group('financial_custody.group_custody_manager'):
            raise UserError(_('Only the custody manager can review and disburse custodies.'))

    def action_approve(self):
        """Approve."""
        self._check_manager()
        for custody in self:
            if custody.state != 'submitted':
                raise UserError(_('Only submitted custodies can be approved.'))
            model_attribute(custody, '_check_previous_custodies')()
        self.write(
            {
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            }
        )
        return True

    def action_refuse(self):
        """Refuse."""
        self._check_manager()
        for custody in self:
            if custody.state not in ('submitted', 'approved'):
                raise UserError(
                    _('Only custodies waiting for review or disbursement can be refused.')
                )
            custody.message_post(
                body=_(
                    'Custody refused by %(user)s. Reason: %(reason)s',
                    user=self.env.user.name,
                    reason=custody.refuse_reason or '-',
                )
            )
        self.write({'state': 'refused'})
        return True

    def action_pay(self):
        """Confirm the disbursement of the custody to the employee and post the accounting entry."""
        self._check_manager()
        for custody in self:
            if custody.state != 'approved':
                raise UserError(_('Only approved custodies can be disbursed.'))
            journal = custody.journal_id or custody.company_id.custody_journal_id
            if not journal or not journal.default_account_id:
                raise UserError(_('Please select a bank or cash journal with a default account.'))
            account = model_attribute(custody, '_get_custody_account')()
            partner = model_attribute(custody, '_get_partner')()
            date = custody.payment_date or fields.Date.context_today(self)
            label = _(
                'Custody %(ref)s - %(employee)s',
                ref=custody.name,
                employee=custody.employee_id.name,
            )
            move = create_custody_entry(
                self.env,
                custody.company_id,
                {
                    'journal_id': journal.id,
                    'date': date,
                    'ref': label,
                    'partner_id': partner.id,
                    'line_ids': [
                        Command.create(
                            {
                                'name': label,
                                'account_id': account.id,
                                'partner_id': partner.id,
                                'debit': custody.amount,
                                'credit': 0.0,
                            }
                        ),
                        Command.create(
                            {
                                'name': label,
                                'account_id': journal.default_account_id.id,
                                'partner_id': partner.id,
                                'debit': 0.0,
                                'credit': custody.amount,
                            }
                        ),
                    ],
                },
            )
            move.action_post()
            custody.write(
                {
                    'state': 'paid',
                    'move_id': move.id,
                    'journal_id': journal.id,
                    'payment_date': date,
                    'paid_by_id': self.env.user.id,
                }
            )
        return True

    def action_cancel(self):
        """Cancel."""
        for custody in self:
            if custody.state in ('paid', 'closed'):
                raise UserError(_('A disbursed custody cannot be cancelled. Settle it instead.'))
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        for custody in self:
            if custody.state not in ('refused', 'cancelled'):
                raise UserError(_('Only refused or cancelled custodies can be reset to draft.'))
        self.write({'state': 'draft'})
        return True

    def _get_custody_account(self):
        self.ensure_one()
        account = self.company_id.custody_account_id
        if not account:
            raise UserError(
                _('Please configure the custody account in Financial Custody settings.')
            )
        return account

    def _get_partner(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(
                _(
                    'Employee %s has no contact. Please set the employee contact on the custody.',
                    self.employee_id.name,
                )
            )
        return self.partner_id

    def _update_closed_state(self):
        for custody in self.filtered(lambda c: c.state == 'paid'):
            custody.invalidate_recordset(['settled_amount', 'balance', 'settled_percent'])
            if float_is_zero(custody.balance, precision_rounding=custody.currency_id.rounding):
                custody.state = 'closed'
                custody.message_post(body=_('The custody is fully settled.'))

    def action_new_settlement(self):
        """New settlement."""
        self.ensure_one()
        if self.state != 'paid':
            raise UserError(_('Only disbursed custodies can be settled.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Custody Settlement'),
            'res_model': 'custody.settlement',
            'view_mode': 'form',
            'context': {'default_custody_id': self.id},
        }

    def action_view_settlements(self):
        """View settlements."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settlements'),
            'res_model': 'custody.settlement',
            'view_mode': 'list,form',
            'domain': [('custody_id', '=', self.id)],
            'context': {'default_custody_id': self.id},
        }

    def action_view_move(self):
        """View move."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('The custody has not been disbursed yet.'))
        return custody_move_action(self.move_id)
