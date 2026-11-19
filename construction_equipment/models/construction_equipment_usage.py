"""Construction equipment construction equipment usage support."""

from datetime import datetime
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero
from .runtime import call_method
from .equipment_fields import request_field


class ConstructionEquipmentUsage(models.Model):
    """Construction Equipment Usage."""

    _name = 'construction.equipment.usage'
    _description = 'Equipment Usage Log'
    _order = 'date desc, id desc'
    equipment_id = fields.Many2one(
        'construction.equipment', string='Equipment', required=True, index=True
    )
    project_id = fields.Many2one(
        'construction.project', string='Project', required=True, index=True
    )
    company_id = fields.Many2one(related='equipment_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='equipment_id.currency_id', string='Currency')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    hours = fields.Float(string='Operating Hours', required=True)
    operating_rate = fields.Monetary(string='Operating Cost / Hour')
    depreciation_rate = fields.Monetary(string='Depreciation / Hour')
    diesel_rate = fields.Float(string='Diesel L / Hour', digits=(16, 3))
    diesel_price = fields.Monetary(string='Diesel Price / L')
    diesel_liters = fields.Float(
        compute='_compute_costs', store=True, string='Diesel (L)', digits=(16, 3)
    )
    operating_cost = fields.Monetary(compute='_compute_costs', store=True, string='Operating Cost')
    depreciation_cost = fields.Monetary(compute='_compute_costs', store=True, string='Depreciation')
    diesel_cost = fields.Monetary(compute='_compute_costs', store=True, string='Diesel Cost')
    total_cost = fields.Monetary(compute='_compute_costs', store=True, string='Total Cost')
    note = fields.Char(string='Work Description')
    state = fields.Selection(
        [('draft', 'Draft'), ('posted', 'Allocated')],
        string='Status',
        default='draft',
        required=True,
        copy=False,
    )
    move_id = fields.Many2one('account.move', string='Allocation Entry', readonly=True, copy=False)
    request_id = request_field('The cost is charged to this request and to its BOQ equipment.')

    @api.depends('equipment_id', 'project_id', 'date')
    def _compute_request_id(self):
        request_model = self.env['construction.equipment.request']
        for usage in self:
            if usage.state == 'posted' and usage.request_id:
                usage.request_id = usage.request_id
                continue
            usage.request_id = call_method(
                request_model,
                '_get_active_request',
                usage.equipment_id,
                usage.project_id,
                usage.date,
            )

    @api.depends('hours', 'operating_rate', 'depreciation_rate', 'diesel_rate', 'diesel_price')
    def _compute_costs(self):
        for usage in self:
            usage.diesel_liters = usage.hours * usage.diesel_rate
            usage.operating_cost = usage.hours * usage.operating_rate
            usage.depreciation_cost = usage.hours * usage.depreciation_rate
            usage.diesel_cost = usage.diesel_liters * usage.diesel_price
            usage.total_cost = usage.operating_cost + usage.depreciation_cost + usage.diesel_cost

    @api.model
    def _get_rate_values(self, equipment):
        return {
            'operating_rate': equipment.operating_cost_per_hour,
            'depreciation_rate': equipment.depreciation_per_hour,
            'diesel_rate': equipment.diesel_per_hour,
            'diesel_price': equipment.diesel_price,
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Create records using the existing equipment defaults and sequencing."""
        equipment_model = self.env['construction.equipment']
        for vals in vals_list:
            equipment = equipment_model.browse(vals.get('equipment_id'))
            if equipment.exists():
                for key, value in self._get_rate_values(equipment).items():
                    vals.setdefault(key, value)
        return super().create(vals_list)

    @api.onchange('equipment_id')
    def _onchange_equipment_id(self):
        for usage in self:
            if usage.equipment_id:
                usage.update(self._get_rate_values(usage.equipment_id))
            if usage.equipment_id.current_project_id:
                usage.project_id = usage.equipment_id.current_project_id

    @api.constrains('equipment_id', 'project_id', 'date', 'hours')
    def _check_equipment_on_project(self):
        for usage in self:
            if not usage.equipment_id or not usage.project_id or (not usage.date):
                continue
            day_logs = self.sudo().search(
                [('equipment_id', '=', usage.equipment_id.id), ('date', '=', usage.date)]
            )
            if sum(day_logs.mapped('hours')) > 24.0 + 1e-06:
                raise ValidationError(
                    _(
                        '%(equipment)s cannot work more than 24 hours on %(date)s.',
                        equipment=usage.equipment_id.display_name,
                        date=usage.date,
                    )
                )
            if usage.request_id:
                continue
            location = call_method(
                usage.equipment_id,
                '_get_project_at',
                datetime.combine(usage.date, datetime.max.time()).replace(microsecond=0),
            )
            if location != usage.project_id:
                raise ValidationError(
                    _(
                        (
                            '%(equipment)s was not on project %(project)s on '
                            '%(date)s: log its hours on the project where it '
                            'worked.'
                        ),
                        equipment=usage.equipment_id.display_name,
                        project=usage.project_id.display_name,
                        date=usage.date,
                    )
                )

    @api.constrains('hours')
    def _check_hours(self):
        for usage in self:
            if usage.hours <= 0 or usage.hours > 24:
                raise ValidationError(_('Operating hours per log must be between 0 and 24.'))

    def write(self, vals):
        """Update records while preserving the equipment workflow checks."""
        if {
            'hours',
            'equipment_id',
            'project_id',
            'date',
            'operating_rate',
            'depreciation_rate',
            'diesel_rate',
            'diesel_price',
            'request_id',
        }.intersection(vals):
            for usage in self:
                if usage.state == 'posted':
                    raise UserError(_('Allocated usage logs cannot be modified.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_equipment_usage(self):
        for usage in self:
            if usage.state == 'posted':
                raise UserError(_('Allocated usage logs cannot be deleted.'))

    def action_post(self):
        """Action post."""
        if not (
            self.env.user.has_group('construction_management.group_construction_transport')
            or self.env.user.has_group('construction_management.group_construction_finance')
            or self.env.user.has_group('construction_management.group_construction_manager')
        ):
            raise UserError(_('You are not allowed to allocate equipment costs.'))
        for usage in self:
            if usage.state != 'draft':
                raise UserError(_('Only draft usage logs can be allocated.'))
            if float_is_zero(usage.total_cost, precision_rounding=usage.currency_id.rounding):
                usage.state = 'posted'
                continue
            project = usage.project_id
            expense_account = call_method(
                project, '_get_company_account', 'construction_equipment_expense_account_id'
            )
            income_account = call_method(
                project, '_get_company_account', 'construction_equipment_income_account_id'
            )
            label = _(
                '%(equipment)s - %(hours)s h - %(date)s',
                equipment=usage.equipment_id.display_name,
                hours=usage.hours,
                date=usage.date,
            )
            move = (
                self.env['account.move']
                .sudo()
                .with_company(usage.company_id)
                .create(
                    {
                        'move_type': 'entry',
                        'journal_id': call_method(project, '_get_misc_journal').id,
                        'date': usage.date,
                        'ref': label,
                        'construction_project_id': project.id,
                        'line_ids': [
                            Command.create(
                                {
                                    'name': label,
                                    'account_id': expense_account.id,
                                    'debit': usage.total_cost,
                                    'credit': 0.0,
                                    'analytic_distribution': call_method(
                                        project, '_get_analytic_distribution'
                                    ),
                                    **call_method(usage, '_get_cost_line_values'),
                                }
                            ),
                            Command.create(
                                {
                                    'name': label,
                                    'account_id': income_account.id,
                                    'debit': 0.0,
                                    'credit': usage.total_cost,
                                    'analytic_distribution': call_method(
                                        usage.equipment_id, '_get_analytic_distribution'
                                    ),
                                }
                            ),
                        ],
                    }
                )
            )
            move.action_post()
            usage.write({'state': 'posted', 'move_id': move.id})
        return True

    def _get_cost_line_values(self):
        self.ensure_one()
        if self.request_id:
            return call_method(self.request_id, '_get_cost_line_values')
        return {'construction_cost_type': 'equipment'}
