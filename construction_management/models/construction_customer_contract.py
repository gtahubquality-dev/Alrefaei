"""Construction customer contract for construction management."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .construction_common import cascade_project_field, workflow_status_field


class ConstructionCustomerContract(models.Model):
    """Contract signed with the customer for a construction project.

    Read-only document: the commercial terms (advance payment, retention, final insurance, deduction
    policy) and the BOQ are shown from the project, where they are maintained, so there is a single
    source of truth. The contract value is frozen when the contract is signed (later changes come
    from change orders).
    """

    _name = 'construction.customer.contract'
    _description = 'Customer Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Contract Number',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    project_id = cascade_project_field()
    partner_id = fields.Many2one(related='project_id.partner_id', store=True, string='Customer')
    owner_id = fields.Many2one(related='project_id.owner_id', string='Project Owner')
    consultant_id = fields.Many2one(related='project_id.consultant_id', string='Consultant')
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    date = fields.Date(
        string='Contract Date', required=True, default=fields.Date.context_today, tracking=True
    )
    signed_date = fields.Date(string='Signed On', readonly=True, copy=False, tracking=True)
    signed_by_id = fields.Many2one('res.users', string='Signed By', readonly=True, copy=False)
    start_date = fields.Date(related='project_id.start_date', string='Start Date')
    duration_months = fields.Integer(
        related='project_id.duration_months', string='Duration (Months)'
    )
    end_date = fields.Date(related='project_id.end_date', string='End Date')

    contract_amount = fields.Monetary(
        related='project_id.contract_amount', string='Current Contract Value'
    )
    original_amount = fields.Monetary(
        related='project_id.original_amount', string='Original Contract Value'
    )
    change_order_amount = fields.Monetary(
        related='project_id.change_order_amount', string='Change Orders'
    )
    signed_amount = fields.Monetary(
        string='Signed Contract Value', readonly=True, copy=False, tracking=True
    )

    advance_payment_percent = fields.Float(
        compute='_compute_terms', store=True, string='Advance Payment (%)'
    )
    advance_payment_amount = fields.Monetary(
        compute='_compute_terms', store=True, string='Agreed Advance Payment'
    )
    advance_deduction_percent = fields.Float(
        compute='_compute_terms', store=True, string='Advance Recovery per Invoice (%)'
    )
    guarantee_percent = fields.Float(compute='_compute_terms', store=True, string='Retention (%)')
    final_insurance_percent = fields.Float(
        compute='_compute_terms', store=True, string='Final Insurance (%)'
    )
    final_insurance_amount = fields.Monetary(
        compute='_compute_terms', store=True, string='Final Insurance Amount'
    )
    boq_item_ids = fields.One2many(related='project_id.boq_item_ids', string='Bill of Quantities')
    deduction_ids = fields.One2many(related='project_id.deduction_ids', string='Deductions')
    invoiced_amount = fields.Monetary(related='project_id.invoiced_amount', string='Invoiced')
    owner_invoice_count = fields.Integer(
        related='project_id.owner_invoice_count', string='Owner Invoices'
    )
    terms = fields.Html(
        string='Terms & Conditions',
        default=lambda self: self.env.company.construction_customer_contract_terms,
    )
    state = workflow_status_field(
        [('draft', 'Draft'), ('signed', 'Signed'), ('closed', 'Closed'), ('cancelled', 'Cancelled')]
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.customer.contract'
                ) or _('New')
        return super().create(vals_list)

    TERM_FIELDS = (
        'advance_payment_percent',
        'advance_payment_amount',
        'advance_deduction_percent',
        'guarantee_percent',
        'final_insurance_percent',
        'final_insurance_amount',
    )

    @api.depends('state', *('project_id.' + name for name in TERM_FIELDS))
    def _compute_terms(self):
        for contract in self:
            follow = (
                contract.state in ('draft', 'cancelled', False)
                or not contract.signed_date
                or not any(contract[name] for name in self.TERM_FIELDS)
            )
            for name in self.TERM_FIELDS:
                contract[name] = contract.project_id[name] if follow else contract[name]

    @api.constrains('project_id', 'state')
    def _check_one_contract(self):
        for contract in self.filtered(lambda c: c.state != 'cancelled'):
            other = self.search(
                [
                    ('id', '!=', contract.id),
                    ('project_id', '=', contract.project_id.id),
                    ('state', '!=', 'cancelled'),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(
                    _(
                        'Project %(project)s already has a customer contract (%(contract)s).',
                        project=contract.project_id.display_name,
                        contract=other.name,
                    )
                )

    def write(self, vals):
        """Write."""
        if 'project_id' in vals and any(
            contract.project_id.id != vals['project_id'] for contract in self
        ):
            raise UserError(_('The project of a customer contract cannot be changed.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_signed(self):
        for contract in self:
            if contract.state not in ('draft', 'cancelled'):
                raise UserError(_('Signed customer contracts cannot be deleted.'))

    def _check_manager(self):
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can sign or close customer contracts.'))

    def action_sign(self):
        """Sign."""
        self._check_manager()
        for contract in self:
            if contract.state != 'draft':
                raise UserError(_('Only draft contracts can be signed.'))
            if not contract.boq_item_ids:
                raise UserError(
                    _(
                        'The project %s has no BOQ: the contract value is unknown.',
                        contract.project_id.display_name,
                    )
                )
        for contract in self:
            contract.write(
                {
                    'state': 'signed',
                    'signed_date': fields.Date.context_today(contract),
                    'signed_by_id': self.env.user.id,
                    'signed_amount': contract.contract_amount,
                }
            )
        return True

    def action_close(self):
        """Close."""
        self._check_manager()
        for contract in self:
            if contract.state != 'signed':
                raise UserError(_('Only signed contracts can be closed.'))
        self.write({'state': 'closed'})
        return True

    def action_cancel(self):
        """Cancel."""
        self._check_manager()
        for contract in self:
            if contract.state == 'closed':
                raise UserError(_('Closed contracts cannot be cancelled.'))
            if contract.project_id.owner_invoice_ids.filtered(lambda inv: inv.state != 'cancelled'):
                raise UserError(
                    _(
                        'Contract %s already has owner invoices: it cannot be cancelled.',
                        contract.name,
                    )
                )
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        for contract in self:
            if contract.state != 'cancelled':
                raise UserError(_('Only cancelled contracts can be reset to draft.'))
        self.write(
            {'state': 'draft', 'signed_date': False, 'signed_by_id': False, 'signed_amount': 0.0}
        )
        return True

    def action_view_project(self):
        """View project."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'construction.project',
            'res_id': self.project_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    def action_view_owner_invoices(self):
        """View owner invoices."""
        self.ensure_one()
        return self.project_id.action_view_owner_invoices()
