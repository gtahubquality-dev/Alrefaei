"""Construction project employee for construction management."""

import calendar
from datetime import timedelta
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from .construction_workforce import PROJECT_ROLES

from .runtime import model_attribute

from .construction_common import cascade_project_field


class ConstructionProjectEmployee(models.Model):
    """Construction project employee."""

    _name = 'construction.project.employee'
    _description = 'Project Workforce'
    _inherit = ['mail.thread']
    _order = 'project_id, date_start desc, id'

    project_id = cascade_project_field()
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    worker_type = fields.Selection(
        [
            ('staff', 'Company Employee'),
            ('external', 'External Labor'),
        ],
        string='Worker Type',
        required=True,
        default='staff',
        tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee.public',
        string='Employee',
        index=True,
        domain="[('company_id', 'in', (company_id, False))]",
    )
    labor_supplier_id = fields.Many2one(
        'res.partner', string='Labor Supplier', help="Manpower supplier of external workers."
    )
    name = fields.Char(string='Name', required=True, tracking=True)
    project_role = fields.Selection(
        PROJECT_ROLES, string='Role on Project', required=True, default='worker', tracking=True
    )
    job_title = fields.Char(string='Job Title')
    identification_no = fields.Char(string='ID / Iqama Number')
    nationality_id = fields.Many2one('res.country', string='Nationality')
    phone = fields.Char(string='Phone')
    date_start = fields.Date(
        string='Assignment Start', required=True, default=fields.Date.context_today, tracking=True
    )
    date_end = fields.Date(string='Assignment End', tracking=True)
    cost_basis = fields.Selection(
        [
            ('monthly', 'Monthly'),
            ('daily', 'Daily'),
        ],
        string='Cost Basis',
        required=True,
        default='monthly',
    )
    rate = fields.Monetary(
        string='Cost Rate',
        tracking=True,
        help="Monthly or daily cost (salary, allowances, housing...) charged to the project.",
    )
    state = fields.Selection(
        [
            ('planned', 'Planned'),
            ('active', 'On Project'),
            ('ended', 'Released'),
        ],
        string='Status',
        compute='_compute_state',
        search='_search_state',
    )
    days_on_project = fields.Integer(string='Days on Project', compute='_compute_cost')
    estimated_cost = fields.Monetary(string='Cost to Date', compute='_compute_cost')
    cost_line_ids = fields.One2many(
        'construction.labor.cost.line', 'assignment_id', string='Allocated Costs'
    )
    allocated_cost = fields.Monetary(string='Allocated Cost', compute='_compute_cost')
    note = fields.Text(string='Notes')

    @api.depends('date_start', 'date_end')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for assignment in self:
            if assignment.date_start and assignment.date_start > today:
                assignment.state = 'planned'
            elif assignment.date_end and assignment.date_end < today:
                assignment.state = 'ended'
            else:
                assignment.state = 'active'

    def _search_state(self, operator, value):
        if operator not in ('=', '!=', 'in', 'not in'):
            raise UserError(_('Unsupported search on status.'))
        today = fields.Date.context_today(self)
        domains = {
            'planned': [('date_start', '>', today)],
            'active': [
                ('date_start', '<=', today),
                '|',
                ('date_end', '=', False),
                ('date_end', '>=', today),
            ],
            'ended': [('date_end', '<', today)],
        }
        values = [value] if isinstance(value, str) else list(value or [])
        domain = (
            Domain.OR([Domain(domains[v]) for v in values if v in domains])
            if values
            else Domain.FALSE
        )
        return domain if operator in ('=', 'in') else ~domain

    @api.depends('date_start', 'date_end', 'rate', 'cost_basis', 'cost_line_ids.amount')
    def _compute_cost(self):
        today = fields.Date.context_today(self)
        for assignment in self:
            days = 0
            cost = 0.0
            if assignment.date_start and assignment.date_start <= today:
                end = min(assignment.date_end or today, today)
                days = max((end - assignment.date_start).days + 1, 0)
                cost = model_attribute(assignment, '_cost_for_period')(assignment.date_start, end)
            assignment.days_on_project = days
            assignment.estimated_cost = cost
            assignment.allocated_cost = sum(assignment.cost_line_ids.mapped('amount'))

    def _cost_for_period(self, date_from, date_to):
        """Cost of the assignment between two dates (included): daily rate x days, or the monthly
        rate shared over the actual number of days of each calendar month.
        """
        self.ensure_one()
        if not date_from or not date_to or date_to < date_from:
            return 0.0
        if self.cost_basis != 'monthly':
            return self.rate * ((date_to - date_from).days + 1)
        cost = 0.0
        current = date_from
        while current <= date_to:
            month_days = calendar.monthrange(current.year, current.month)[1]
            month_end = current.replace(day=month_days)
            period_end = min(month_end, date_to)
            cost += self.rate * ((period_end - current).days + 1) / month_days
            current = period_end + timedelta(days=1)
        return self.currency_id.round(cost) if self.currency_id else cost

    def _cost_for_days(self, days):
        self.ensure_one()
        if self.cost_basis == 'monthly':
            return (
                self.currency_id.round(self.rate * days / 30.0)
                if self.currency_id
                else self.rate * days / 30.0
            )
        return self.rate * days

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for assignment in self:
            employee = assignment.employee_id
            if employee:
                assignment.name = employee.name
                assignment.job_title = employee.job_title or employee.job_id.name
                assignment.phone = employee.mobile_phone or employee.work_phone

    @api.model_create_multi
    def create(self, vals_list):
        """Records created without the form (imports, other modules) take the name of their
        employee."""
        for vals in vals_list:
            if vals.get('employee_id') and not vals.get('name'):
                employee = self.env['hr.employee.public'].browse(vals['employee_id'])
                vals['name'] = employee.name
                vals.setdefault('job_title', employee.job_title or employee.job_id.name)
        return super().create(vals_list)

    @api.constrains('date_start', 'date_end', 'rate')
    def _check_values(self):
        for assignment in self:
            if assignment.date_end and assignment.date_end < assignment.date_start:
                raise ValidationError(_('The assignment end date cannot be before its start date.'))
            if assignment.rate < 0:
                raise ValidationError(_('The cost rate cannot be negative.'))

    @api.constrains('employee_id', 'date_start', 'date_end', 'project_id')
    def _check_overlap(self):
        released = self.env.cr.cache.get('construction_released_assignments', set())
        for assignment in self.filtered(lambda a: a.employee_id and a.id not in released):
            domain = [
                ('id', '!=', assignment.id),
                ('employee_id', '=', assignment.employee_id.id),
                '|',
                ('date_end', '=', False),
                ('date_end', '>=', assignment.date_start),
            ]
            if assignment.date_end:
                domain.append(('date_start', '<=', assignment.date_end))
            other = self.sudo().search(domain, limit=1)
            if other:
                raise ValidationError(
                    _(
                        '%(employee)s is already assigned to project %(project)s for an overlapping'
                        ' period: release them first.',
                        employee=assignment.name,
                        project=other.project_id.display_name,
                    )
                )

    def action_release(self):
        """End the assignment today. Shortening a period never creates an overlap: allowed even when
        older data has overlapping assignments of the same employee.
        """
        today = fields.Date.context_today(self)

        released = self.env.cr.cache.setdefault('construction_released_assignments', set())
        released.update(self.ids)
        try:
            for assignment in self:
                if not assignment.date_end or assignment.date_end > today:
                    assignment.date_end = max(today, assignment.date_start)
            self.flush_recordset()
        finally:
            released.difference_update(self.ids)
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_project_employee(self):
        if self.cost_line_ids:
            raise UserError(
                _(
                    'Workforce assignments with allocated costs cannot be deleted. Release them'
                    ' instead.'
                )
            )
