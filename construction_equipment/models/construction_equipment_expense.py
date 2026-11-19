"""Construction equipment construction equipment expense support."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
from .runtime import call_method
from .equipment_fields import reference_field, tracked_equipment_field, status_field, request_field


class ConstructionEquipmentExpense(models.Model):
    """Construction Equipment Expense."""

    _name = 'construction.equipment.expense'
    _description = 'Equipment Expense'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    name = reference_field()
    equipment_id = tracked_equipment_field()
    expense_datetime = fields.Datetime(
        string='Expense Date & Time', required=True, default=fields.Datetime.now, tracking=True
    )
    project_id = fields.Many2one(
        'construction.project',
        string='Project',
        index=True,
        tracking=True,
        compute='_compute_project_id',
        store=True,
        readonly=False,
        help=(
            'The full expense is charged to the project where '
            'the equipment was located at the time of the '
            'expense, whatever the time it stays there. Empty = '
            'main yard.'
        ),
    )
    company_id = fields.Many2one(related='equipment_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='equipment_id.currency_id', string='Currency')
    expense_type = fields.Selection(
        [
            ('maintenance', 'Maintenance'),
            ('repair', 'Repair'),
            ('rental', 'Rental'),
            ('fuel', 'Fuel (Diesel)'),
            ('oil', 'Oil & Lubricants'),
            ('transport', 'Transport'),
            ('other', 'Other'),
        ],
        string='Expense Type',
        required=True,
        default='maintenance',
        tracking=True,
    )
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    vendor_reference = fields.Char(string='Vendor Invoice No.')
    date = fields.Date(string='Date', compute='_compute_date', store=True)
    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    description = fields.Char(string='Description')
    state = status_field(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted to Accountant'),
            ('billed', 'Recorded'),
            ('cancelled', 'Cancelled'),
        ]
    )
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    move_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False)
    request_id = request_field(('The expense is charged to this request and to its BOQ equipment.'))

    @api.depends('equipment_id', 'project_id', 'date')
    def _compute_request_id(self):
        request_model = self.env['construction.equipment.request']
        for expense in self:
            if expense.state == 'billed' and expense.request_id:
                expense.request_id = expense.request_id
                continue
            expense.request_id = call_method(
                request_model,
                '_get_active_request',
                expense.equipment_id,
                expense.project_id,
                expense.date,
            )

    @api.constrains('amount')
    def _check_amount(self):
        for expense in self:
            if float_compare(expense.amount, 0.0, precision_digits=6) <= 0:
                raise ValidationError(_('The expense amount must be positive.'))

    @api.depends('equipment_id', 'expense_datetime')
    def _compute_project_id(self):
        for expense in self:
            if expense.equipment_id and expense.expense_datetime:
                expense.project_id = call_method(
                    expense.equipment_id, '_get_project_at', expense.expense_datetime
                )
            else:
                expense.project_id = False

    @api.depends('expense_datetime')
    def _compute_date(self):
        for expense in self:
            expense.date = (
                fields.Datetime.context_timestamp(expense, expense.expense_datetime).date()
                if expense.expense_datetime
                else False
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Create records using the existing equipment defaults and sequencing."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.equipment.expense'
                ) or _('New')
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_equipment_expense(self):
        for expense in self:
            if expense.state == 'billed':
                raise UserError(_('Recorded expenses cannot be deleted.'))

    def action_submit(self):
        """Action submit."""
        for expense in self:
            if expense.state != 'draft':
                raise UserError(_('Only draft expenses can be submitted.'))
        self.write({'state': 'submitted', 'submitted_by_id': self.env.user.id})
        return True

    def action_create_bill(self):
        """Action create bill."""
        if not self.env.user.has_group('construction_management.group_construction_finance'):
            raise UserError(_('Only the accountant can record equipment expenses.'))
        for expense in self:
            if expense.state != 'submitted':
                raise UserError(_('Only submitted expenses can be recorded.'))
            if not expense.vendor_id:
                raise UserError(_('Please set the vendor of expense %s.', expense.name))
            account = expense.company_id.construction_equipment_cost_account_id
            if not account:
                raise UserError(
                    _(
                        (
                            'Please configure the equipment maintenance / rental '
                            'expense account in Construction settings.'
                        )
                    )
                )
            description = (
                expense.description
                or dict(self._fields['expense_type'].selection)[expense.expense_type]
            )
            label = f'{expense.equipment_id.display_name!s} - {description!s}'
            move = (
                self.env['account.move']
                .sudo()
                .with_company(expense.company_id)
                .create(
                    {
                        'move_type': 'in_invoice',
                        'partner_id': expense.vendor_id.id,
                        'invoice_date': expense.date,
                        'ref': expense.vendor_reference or expense.name,
                        'invoice_origin': expense.name,
                        'company_id': expense.company_id.id,
                        'construction_project_id': expense.project_id.id,
                        'invoice_line_ids': [
                            Command.create(
                                {
                                    'name': label,
                                    'quantity': 1.0,
                                    'price_unit': expense.amount,
                                    'account_id': account.id,
                                    'analytic_distribution': call_method(
                                        expense.equipment_id,
                                        '_get_analytic_distribution',
                                        expense.project_id,
                                    ),
                                    **(
                                        call_method(expense.request_id, '_get_cost_line_values')
                                        if expense.request_id
                                        else {'construction_cost_type': 'equipment'}
                                    ),
                                }
                            )
                        ],
                    }
                )
            )
            expense.write({'state': 'billed', 'move_id': move.id})
        return True

    def action_cancel(self):
        """Action cancel."""
        for expense in self:
            if expense.state == 'billed':
                raise UserError(
                    _(('Recorded expenses cannot be cancelled. Cancel the vendor bill instead.'))
                )
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Action reset draft."""
        for expense in self:
            if expense.state != 'cancelled':
                raise UserError(_('Only cancelled expenses can be reset to draft.'))
        self.write({'state': 'draft'})
        return True

    def action_view_bill(self):
        """Action view bill."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('No vendor bill has been created yet.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }
