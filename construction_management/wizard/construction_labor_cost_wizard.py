"""Construction labor cost wizard for construction management."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

from ..models.invoice_adjustments import journal_entry_action
from ..models.runtime import model_attribute


class ConstructionLaborCostWizard(models.TransientModel):
    """Construction labor cost wizard."""

    _name = 'construction.labor.cost.wizard'
    _description = 'Allocate Project Labor Cost'

    project_id = fields.Many2one('construction.project', string='Project', required=True)
    company_id = fields.Many2one(related='project_id.company_id', string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
    line_ids = fields.One2many(
        'construction.labor.cost.wizard.line', 'wizard_id', string='Workforce'
    )
    amount_total = fields.Monetary(compute='_compute_amount_total', string='Total')

    @api.model
    def default_get(self, fields_list):
        """Default get."""
        values = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        values.setdefault('date_from', today.replace(day=1))
        values.setdefault('date_to', today)
        return values

    @api.depends('line_ids.amount')
    def _compute_amount_total(self):
        for wizard in self:
            wizard.amount_total = sum(wizard.line_ids.mapped('amount'))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_to < wizard.date_from:
                raise ValidationError(_('The end date cannot be before the start date.'))

    @api.onchange('project_id', 'date_from', 'date_to')
    def _onchange_period(self):
        for wizard in self:
            wizard.line_ids = [Command.clear()] + [
                Command.create(vals) for vals in model_attribute(wizard, '_prepare_lines')()
            ]

    def _prepare_lines(self):
        self.ensure_one()
        if (
            not (self.project_id and self.date_from and self.date_to)
            or self.date_to < self.date_from
        ):
            return []
        lines = []
        assignments = self.env['construction.project.employee'].search(
            [
                ('project_id', '=', self.project_id.id),
                ('date_start', '<=', self.date_to),
                '|',
                ('date_end', '=', False),
                ('date_end', '>=', self.date_from),
            ]
        )
        for assignment in assignments:
            start = max(assignment.date_start, self.date_from)
            end = min(assignment.date_end or self.date_to, self.date_to)
            days = (end - start).days + 1
            if days <= 0:
                continue
            lines.append(
                {
                    'assignment_id': assignment.id,
                    'date_from': start,
                    'date_to': end,
                    'days': days,
                    'amount': model_attribute(assignment, '_cost_for_period')(start, end),
                }
            )
        return lines

    def action_allocate(self):
        """Allocate."""
        self.ensure_one()
        if not (
            self.env.user.has_group('construction_management.group_construction_finance')
            or self.env.user.has_group('construction_management.group_construction_manager')
        ):
            raise UserError(_('Only Finance or Senior Management can allocate labor costs.'))
        if not self.line_ids:
            self.line_ids = [Command.create(vals) for vals in self._prepare_lines()]
        lines = self.line_ids.filtered(
            lambda l: not float_is_zero(l.amount, precision_rounding=self.currency_id.rounding)
        )
        if not lines:
            raise UserError(_('There is no labor cost to allocate for this period.'))
        cost_line_model = self.env['construction.labor.cost.line'].sudo()
        for line in lines:
            overlap = cost_line_model.search_count(
                [
                    ('assignment_id', '=', line.assignment_id.id),
                    ('date_from', '<=', line.date_to),
                    ('date_to', '>=', line.date_from),
                ]
            )
            if overlap:
                raise UserError(
                    _(
                        'The cost of %(name)s has already been allocated for part of this period.',
                        name=line.assignment_id.name,
                    )
                )
        project = self.project_id
        expense = model_attribute(project, '_get_company_account')(
            'construction_labor_expense_account_id'
        )
        accrual = model_attribute(project, '_get_company_account')(
            'construction_labor_accrual_account_id'
        )
        distribution = model_attribute(project, '_get_analytic_distribution')()
        ref = _(
            'Labor cost %(project)s %(start)s - %(end)s',
            project=project.code,
            start=self.date_from,
            end=self.date_to,
        )
        move_lines = [
            Command.create(
                {
                    'name': f'{line.assignment_id.name} ({line.days} d)',
                    'account_id': expense.id,
                    'debit': line.amount,
                    'credit': 0.0,
                    'analytic_distribution': distribution,
                    'construction_cost_type': 'labor',
                    'construction_boq_component_id': line.assignment_id.boq_component_id.id,
                    'construction_boq_item_id': line.assignment_id.boq_component_id.item_id.id,
                }
            )
            for line in lines
        ]
        move_lines.append(
            Command.create(
                {
                    'name': ref,
                    'account_id': accrual.id,
                    'debit': 0.0,
                    'credit': sum(lines.mapped('amount')),
                }
            )
        )
        move = (
            self.env['account.move']
            .sudo()
            .with_company(project.company_id)
            .create(
                {
                    'move_type': 'entry',
                    'journal_id': model_attribute(project, '_get_misc_journal')().id,
                    'date': self.date_to,
                    'ref': ref,
                    'construction_project_id': project.id,
                    'line_ids': move_lines,
                }
            )
        )
        move.action_post()
        cost_line_model.create(
            [
                {
                    'assignment_id': line.assignment_id.id,
                    'date_from': line.date_from,
                    'date_to': line.date_to,
                    'days': line.days,
                    'amount': line.amount,
                    'move_id': move.id,
                }
                for line in lines
            ]
        )
        project.message_post(
            body=_(
                'Labor cost of %(amount)s allocated (%(ref)s).', amount=move.amount_total, ref=ref
            )
        )
        return journal_entry_action(move)


class ConstructionLaborCostWizardLine(models.TransientModel):
    """Construction labor cost wizard line."""

    _name = 'construction.labor.cost.wizard.line'
    _description = 'Allocate Project Labor Cost Line'

    wizard_id = fields.Many2one('construction.labor.cost.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id', string='Currency')
    assignment_id = fields.Many2one(
        'construction.project.employee', string='Workforce Assignment', required=True
    )
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    days = fields.Integer(string='Days')
    amount = fields.Monetary(string='Amount')
