"""Construction fleet construction vehicle sheet support."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
from odoo.addons.construction_equipment.models.runtime import call_method


class ConstructionVehicleSheet(models.Model):
    """Construction Vehicle Sheet."""

    _name = 'construction.vehicle.sheet'
    _description = 'Vehicle Driver Custody Sheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'
    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New')
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    vehicle_id = fields.Many2one(
        'construction.equipment',
        string='Vehicle',
        required=True,
        tracking=True,
        domain="[('company_id', '=', company_id)]",
    )
    driver_id = fields.Many2one(
        'construction.driver',
        string='Driver',
        required=True,
        tracking=True,
        compute='_compute_driver_id',
        store=True,
        readonly=False,
        precompute=True,
    )
    employee_id = fields.Many2one(related='driver_id.employee_id', string='Driver Employee')
    custody_id = fields.Many2one(
        'custody.request',
        string='Driver Custody',
        tracking=True,
        domain="[('employee_id', '=', employee_id), ('state', '=', 'paid')]",
    )
    custody_amount = fields.Monetary(compute='_compute_custody_info', string='Custody Received')
    custody_balance = fields.Monetary(compute='_compute_custody_info', string='Custody Balance')
    date_from = fields.Date(
        string='From', required=True, default=fields.Date.context_today, tracking=True
    )
    date_to = fields.Date(
        string='To', required=True, default=fields.Date.context_today, tracking=True
    )
    trip_ids = fields.One2many(
        'construction.vehicle.sheet.trip', 'sheet_id', string='Trips', copy=True
    )
    expense_ids = fields.One2many(
        'construction.vehicle.sheet.expense', 'sheet_id', string='Other Expenses', copy=True
    )
    allocation_method = fields.Selection(
        [('quantity', 'By Transported Quantity'), ('value', 'By Trip Value')],
        string='Distribute Other Expenses',
        required=True,
        default='quantity',
        tracking=True,
        help=(
            'Other expenses added to the cost of the trips: share of each trip = '
            'its transported quantity (or value) divided by the total '
            'transported (or total value) of the sheet.'
        ),
    )
    trips_quantity = fields.Float(
        compute='_compute_totals', store=True, string='Total Transported', digits='Product Unit'
    )
    trips_amount = fields.Monetary(compute='_compute_totals', store=True, string='Trips Value')
    other_amount = fields.Monetary(
        compute='_compute_totals', store=True, string='Other Expenses Total'
    )
    total_amount = fields.Monetary(compute='_compute_totals', store=True, string='Total Cost')
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted for Settlement'),
            ('done', 'Settled'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )
    settlement_id = fields.Many2one(
        'custody.settlement', string='Custody Settlement', readonly=True, copy=False
    )
    note = fields.Text(string='Driver Notes')

    @api.depends('vehicle_id')
    def _compute_driver_id(self):
        for sheet in self:
            if sheet.vehicle_id.driver_id:
                sheet.driver_id = sheet.vehicle_id.driver_id
            elif not sheet.driver_id:
                sheet.driver_id = False

    def _compute_custody_info(self):
        for sheet in self:
            custody = sheet.sudo().custody_id
            sheet.custody_amount = custody.amount
            sheet.custody_balance = custody.balance

    @api.depends('trip_ids.quantity', 'trip_ids.amount', 'expense_ids.amount')
    def _compute_totals(self):
        for sheet in self:
            sheet.trips_quantity = sum(sheet.trip_ids.mapped('quantity'))
            sheet.trips_amount = sum(sheet.trip_ids.mapped('amount'))
            sheet.other_amount = sum(sheet.expense_ids.mapped('amount'))
            sheet.total_amount = sheet.trips_amount + sheet.other_amount

    def _get_distributed_expenses(self):
        self.ensure_one()
        return self.expense_ids.filtered('distribute')

    @api.constrains('date_from', 'date_to', 'vehicle_id')
    def _check_sheet(self):
        for sheet in self:
            if sheet.date_to < sheet.date_from:
                raise ValidationError(_('The end date cannot be before the start date.'))
            if sheet.vehicle_id and (not sheet.vehicle_id.is_vehicle):
                raise ValidationError(
                    _(
                        '%s is a machine, not a vehicle. Driver custody sheets are for vehicles.',
                        sheet.vehicle_id.display_name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Create records using the existing defaults and sequence values."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.vehicle.sheet'
                ) or _('New')
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_vehicle_sheet(self):
        for sheet in self:
            if sheet.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled sheets can be deleted.'))

    def _check_lines(self):
        for sheet in self:
            if not sheet.trip_ids and (not sheet.expense_ids):
                raise UserError(_('Please enter the trips and expenses of the driver.'))
            for trip in sheet.trip_ids:
                if float_compare(trip.amount, 0.0, precision_digits=6) < 0 or trip.quantity < 0:
                    raise ValidationError(_('Trip values and quantities cannot be negative.'))
                if not trip.project_id:
                    raise ValidationError(_('Please select the project of every trip.'))
                if not sheet.date_from <= trip.date <= sheet.date_to:
                    raise ValidationError(_('Trip dates must be within the sheet period.'))
            for expense in sheet.expense_ids:
                if float_compare(expense.amount, 0.0, precision_digits=6) <= 0:
                    raise ValidationError(_('Expense amounts must be positive.'))
                if not expense.distribute and (not expense.project_id):
                    raise ValidationError(
                        _('Please select the project of the expense "%s".', expense.name)
                    )
                if expense.date and (not sheet.date_from <= expense.date <= sheet.date_to):
                    raise ValidationError(_('Expense dates must be within the sheet period.'))
            if call_method(sheet, '_get_distributed_expenses') and (not sheet.trip_ids):
                raise UserError(
                    _(
                        (
                            'Other expenses are distributed on the trips: please enter '
                            'at least one trip.'
                        )
                    )
                )

    def action_submit(self):
        """Create the driver custody settlement from trips and distributed expenses."""
        if not self.env.user.has_group('construction_management.group_construction_user'):
            raise UserError(_('You are not allowed to submit driver custody sheets.'))
        for sheet in self:
            if sheet.state != 'draft':
                raise UserError(_('Only draft sheets can be submitted.'))
            call_method(sheet, '_check_lines')
            custody = sheet.sudo().custody_id
            if not custody:
                raise UserError(_('Please select the driver custody.'))
            if custody.state != 'paid':
                raise UserError(_('Custody %s is not open for settlement.', custody.name))
            if (
                not sheet.driver_id.employee_id
                or custody.employee_id != sheet.driver_id.employee_id
            ):
                raise UserError(
                    _(
                        'Custody %(custody)s does not belong to driver %(driver)s.',
                        custody=custody.name,
                        driver=sheet.driver_id.name,
                    )
                )
            account = (
                sheet.company_id.construction_transport_expense_account_id
                or sheet.company_id.construction_equipment_cost_account_id
            )
            if not account:
                raise UserError(
                    _(
                        (
                            'Please configure the vehicle transport cost account in '
                            'Construction settings.'
                        )
                    )
                )
            lines = []
            for trip in sheet.trip_ids:
                distribution = call_method(
                    sheet.vehicle_id, '_get_analytic_distribution', trip.project_id
                )
                label = _(
                    '%(vehicle)s - %(type)s %(qty)s %(uom)s - %(project)s',
                    vehicle=sheet.vehicle_id.display_name,
                    type=trip.transport_type_id.name or '',
                    qty=trip.quantity,
                    uom=trip.uom_id.name or '',
                    project=trip.project_id.code,
                )
                lines.append(
                    Command.create(
                        {
                            'date': trip.date,
                            'name': label,
                            'invoice_ref': trip.document_ref or sheet.name,
                            'account_id': account.id,
                            'analytic_distribution': distribution,
                            'amount': trip.total_cost,
                        }
                    )
                )
            for expense in sheet.expense_ids.filtered(lambda e: not e.distribute):
                lines.append(
                    Command.create(
                        {
                            'date': expense.date or sheet.date_to,
                            'name': _(
                                '%(vehicle)s - %(expense)s - %(project)s',
                                vehicle=sheet.vehicle_id.display_name,
                                expense=expense.name,
                                project=expense.project_id.code,
                            ),
                            'invoice_ref': expense.invoice_ref or sheet.name,
                            'account_id': account.id,
                            'analytic_distribution': call_method(
                                sheet.vehicle_id, '_get_analytic_distribution', expense.project_id
                            ),
                            'amount': expense.amount,
                        }
                    )
                )
            settlement = (
                self.env['custody.settlement']
                .sudo()
                .create(
                    {
                        'custody_id': custody.id,
                        'date': sheet.date_to,
                        'note': _('Driver custody sheet %s', sheet.name),
                        'vehicle_sheet_id': sheet.id,
                        'line_ids': lines,
                    }
                )
            )
            settlement.action_submit()
            sheet.write({'state': 'submitted', 'settlement_id': settlement.id})
            sheet.message_post(
                body=_('Settlement %s submitted to the custody manager.', settlement.name)
            )
        return True

    def action_cancel(self):
        """Action cancel."""
        for sheet in self:
            if sheet.state == 'done':
                raise UserError(_('Settled sheets cannot be cancelled.'))
            if sheet.settlement_id and sheet.settlement_id.sudo().state != 'cancelled':
                sheet.settlement_id.sudo().action_cancel()
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Action reset draft."""
        for sheet in self:
            if sheet.state != 'cancelled':
                raise UserError(_('Only cancelled sheets can be reset to draft.'))
        self.write({'state': 'draft', 'settlement_id': False})
        return True

    def action_view_settlement(self):
        """Action view settlement."""
        self.ensure_one()
        if not self.settlement_id:
            raise UserError(_('No settlement has been created yet.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'custody.settlement',
            'res_id': self.settlement_id.id,
            'view_mode': 'form',
        }
