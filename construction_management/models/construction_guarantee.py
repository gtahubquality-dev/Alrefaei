"""Construction guarantee for construction management."""

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from .construction_common import (
    project_subcontract_field,
    reference_field,
    restrict_project_field,
    workflow_status_field,
)

GUARANTEE_TYPES = [
    ('bid', 'Bid Bond (Initial Guarantee)'),
    ('final', 'Final Insurance / Performance Bond'),
    ('advance', 'Advance Payment Guarantee'),
    ('retention', 'Work Guarantee (Retention)'),
    ('other', 'Other'),
]
EXPIRY_ALERT_DAYS = 30


class ConstructionGuarantee(models.Model):
    """Construction guarantee."""

    _name = 'construction.guarantee'
    _description = 'Bank / Cash Guarantee'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expiry_date, id'

    name = reference_field()
    project_id = restrict_project_field()
    subcontract_id = project_subcontract_field(tracking=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    direction = fields.Selection(
        [
            ('issued', 'Issued by Us (to Owner)'),
            ('received', 'Received (from Subcontractor)'),
        ],
        string='Direction',
        required=True,
        default='issued',
        tracking=True,
    )
    guarantee_type = fields.Selection(
        GUARANTEE_TYPES, string='Guarantee Type', required=True, default='final', tracking=True
    )
    guarantee_form = fields.Selection(
        [
            ('bank', 'Bank Letter of Guarantee'),
            ('cash', 'Cash'),
        ],
        string='Form',
        required=True,
        default='bank',
        tracking=True,
    )
    bank_id = fields.Many2one('res.bank', string='Bank', tracking=True)
    reference = fields.Char(string='Guarantee Number', tracking=True)
    beneficiary_id = fields.Many2one('res.partner', string='Beneficiary', tracking=True)
    applicant_id = fields.Many2one('res.partner', string='Applicant / Issuer', tracking=True)
    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    percentage = fields.Float(string='Percentage of Contract (%)', compute='_compute_percentage')
    cash_margin = fields.Monetary(string='Cash Margin Held by Bank', tracking=True)
    bank_commission = fields.Monetary(string='Bank Commission')
    issue_date = fields.Date(string='Issue Date', default=fields.Date.context_today, tracking=True)
    expiry_date = fields.Date(string='Expiry Date', tracking=True)
    release_date = fields.Date(string='Release Date', readonly=True, copy=False, tracking=True)
    days_to_expiry = fields.Integer(string='Days to Expiry', compute='_compute_days_to_expiry')
    expiry_alert_sent = fields.Boolean(string='Expiry Alert Sent', copy=False)
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
        help="Bank or cash journal used to pay a cash final insurance.",
    )
    operation_id = fields.Many2one(
        'construction.project.operation', string='Cash Payment', readonly=True, copy=False
    )
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('released', 'Released'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ]
    )
    extension_ids = fields.One2many(
        'construction.guarantee.extension', 'guarantee_id', string='Extensions'
    )
    note = fields.Text(string='Notes')

    @api.depends('amount', 'project_id.contract_amount', 'subcontract_id.amount_total', 'direction')
    def _compute_percentage(self):
        for guarantee in self:
            base = (
                guarantee.subcontract_id.amount_total
                if guarantee.direction == 'received'
                else guarantee.project_id.contract_amount
            )
            guarantee.percentage = guarantee.amount / base * 100.0 if base else 0.0

    @api.depends('expiry_date', 'state')
    def _compute_days_to_expiry(self):
        today = fields.Date.context_today(self)
        for guarantee in self:
            if guarantee.expiry_date and guarantee.state == 'active':
                guarantee.days_to_expiry = (guarantee.expiry_date - today).days
            else:
                guarantee.days_to_expiry = 0

    @api.onchange('direction', 'project_id', 'subcontract_id')
    def _onchange_parties(self):
        for guarantee in self:
            company_partner = guarantee.company_id.partner_id or self.env.company.partner_id
            if guarantee.direction == 'issued':
                guarantee.beneficiary_id = (
                    guarantee.project_id.owner_id or guarantee.project_id.partner_id
                )
                guarantee.applicant_id = company_partner
            else:
                guarantee.beneficiary_id = company_partner
                guarantee.applicant_id = guarantee.subcontract_id.partner_id

    @api.constrains('amount', 'cash_margin', 'bank_commission', 'issue_date', 'expiry_date')
    def _check_values(self):
        for guarantee in self:
            if float_compare(guarantee.amount, 0.0, precision_digits=6) <= 0:
                raise ValidationError(_('The guarantee amount must be positive.'))
            if guarantee.cash_margin < 0 or guarantee.bank_commission < 0:
                raise ValidationError(_('Cash margin and bank commission cannot be negative.'))
            if (
                guarantee.issue_date
                and guarantee.expiry_date
                and guarantee.expiry_date < guarantee.issue_date
            ):
                raise ValidationError(_('The expiry date cannot be before the issue date.'))

    @api.constrains('direction', 'subcontract_id')
    def _check_direction(self):
        for guarantee in self:
            if guarantee.direction == 'received' and not guarantee.subcontract_id:
                raise ValidationError(_('Guarantees received must be linked to a subcontract.'))

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.guarantee') or _(
                    'New'
                )
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_guarantee(self):
        for guarantee in self:
            if guarantee.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled guarantees can be deleted.'))

    def _check_manager(self):
        if not (
            self.env.user.has_group('construction_management.group_construction_finance')
            or self.env.user.has_group('construction_management.group_construction_manager')
        ):
            raise UserError(_('Only Finance or Senior Management can manage guarantees.'))

    def action_activate(self):
        """Activate."""
        self._check_manager()
        for guarantee in self:
            if guarantee.state != 'draft':
                raise UserError(_('Only draft guarantees can be activated.'))
            if guarantee.guarantee_form == 'bank' and not (
                guarantee.bank_id and guarantee.reference and guarantee.expiry_date
            ):
                raise UserError(
                    _('Bank guarantees require the bank, the guarantee number and the expiry date.')
                )
            vals = {'state': 'active'}
            if (
                guarantee.guarantee_form == 'cash'
                and guarantee.direction == 'issued'
                and guarantee.guarantee_type == 'final'
            ):
                if not guarantee.journal_id:
                    raise UserError(
                        _('Please select the payment journal of the cash final insurance.')
                    )
                operation = (
                    self.env['construction.project.operation']
                    .sudo()
                    .create(
                        {
                            'project_id': guarantee.project_id.id,
                            'operation_type': 'insurance_payment',
                            'name': _('Final insurance %s', guarantee.name),
                            'amount': guarantee.amount,
                            'journal_id': guarantee.journal_id.id,
                            'date': guarantee.issue_date or fields.Date.context_today(self),
                        }
                    )
                )
                operation.action_post()
                vals['operation_id'] = operation.id
            guarantee.write(vals)
        return True

    def action_release(self, release_date=None):
        """Release."""
        self._check_manager()
        for guarantee in self:
            if guarantee.state not in ('active', 'expired'):
                raise UserError(_('Only active or expired guarantees can be released.'))
        self.write(
            {'state': 'released', 'release_date': release_date or fields.Date.context_today(self)}
        )
        return True

    def _auto_release(self, guarantee_types, release_date):
        """Release issued guarantees automatically at handover (no user group check)."""
        to_release = self.filtered(
            lambda g: g.state in ('active', 'expired')
            and g.direction == 'issued'
            and g.guarantee_type in guarantee_types
        )
        for guarantee in to_release:
            guarantee.write({'state': 'released', 'release_date': release_date})
            guarantee.message_post(body=_('Released automatically at project handover.'))
        return to_release

    def action_cancel(self):
        """Cancel."""
        for guarantee in self:
            if guarantee.state != 'draft':
                raise UserError(_('Only draft guarantees can be cancelled.'))
        self.write({'state': 'cancelled'})
        return True

    def action_open_extend(self):
        """Open extend."""
        self.ensure_one()
        if self.state not in ('active', 'expired'):
            raise UserError(_('Only active or expired guarantees can be extended.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Extend Guarantee'),
            'res_model': 'construction.guarantee.extend.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_guarantee_id': self.id, 'default_new_amount': self.amount},
        }

    @api.model
    def _cron_check_expiry(self):
        today = fields.Date.context_today(self)
        expired = self.search([('state', '=', 'active'), ('expiry_date', '<', today)])
        for guarantee in expired:
            guarantee.state = 'expired'
            guarantee.message_post(body=_('The guarantee has expired.'))
        soon = self.search(
            [
                ('state', '=', 'active'),
                ('expiry_alert_sent', '=', False),
                ('expiry_date', '<=', today + timedelta(days=EXPIRY_ALERT_DAYS)),
                ('expiry_date', '>=', today),
            ]
        )
        for guarantee in soon:
            user = guarantee.project_id.manager_id or self.env.user
            guarantee.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=guarantee.expiry_date,
                summary=_('Guarantee %s expires soon', guarantee.reference or guarantee.name),
                note=_('Extend or release the guarantee before %s.', guarantee.expiry_date),
                user_id=user.id,
            )
            guarantee.expiry_alert_sent = True
        return True
