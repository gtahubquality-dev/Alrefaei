"""Construction equipment construction equipment dashboard construction equipment
dashboard support."""

from datetime import timedelta
from markupsafe import Markup, escape
from odoo import _, api, fields, models
from odoo.tools.misc import format_date
from .runtime import MODEL_NAME, call_method
from .construction_equipment_dashboard_constants import (
    MACHINE_CATEGORIES,
    COST_GROUPS,
    EXPENSE_GROUP,
    RENTAL_ALERT_DAYS,
)


class ConstructionEquipmentDashboard(models.TransientModel):
    """Dashboard of the machines and equipment (vehicles have their own application).
    Every figure is computed live from the filters: no refresh needed."""

    _name = 'construction.equipment.dashboard'
    _inherit = ['construction.dashboard.mixin']
    _description = 'Machines & Equipment Dashboard'
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    date_from = fields.Date(
        string='Period From',
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    date_to = fields.Date(string='Period To', required=True, default=fields.Date.context_today)
    project_id = fields.Many2one(
        'construction.project',
        string='Project',
        domain="[('company_id', '=', company_id)]",
        help='Only the equipment currently on this project site, and its costs.',
    )
    category = fields.Selection(MACHINE_CATEGORIES, string='Type')
    ownership = fields.Selection(
        [('owned', 'Company Owned'), ('rented', 'Rented')], string='Ownership'
    )
    total_count = fields.Integer(compute='_compute_kpis', string='All Equipment')
    owned_count = fields.Integer(compute='_compute_kpis', string='Company Owned')
    rented_count = fields.Integer(compute='_compute_kpis', string='Rented')
    available_count = fields.Integer(compute='_compute_kpis', string='Available in Yard')
    on_site_count = fields.Integer(compute='_compute_kpis', string='On Project Sites')
    maintenance_count = fields.Integer(compute='_compute_kpis', string='Under Maintenance')
    inactive_count = fields.Integer(compute='_compute_kpis', string='Out of Service')
    in_transit_count = fields.Integer(compute='_compute_kpis', string='In Transit')
    pending_request_count = fields.Integer(compute='_compute_kpis', string='Requests to Process')
    approval_request_count = fields.Integer(
        compute='_compute_kpis', string='Waiting Senior Management'
    )
    pending_expense_count = fields.Integer(compute='_compute_kpis', string='Expenses to Record')
    draft_usage_count = fields.Integer(compute='_compute_kpis', string='Usage Logs to Post')
    rental_alert_count = fields.Integer(compute='_compute_kpis', string='Rentals Ending')
    period_hours = fields.Float(compute='_compute_kpis', string='Operating Hours')
    period_cost = fields.Monetary(compute='_compute_kpis', string='Total Cost')
    period_usage_cost = fields.Monetary(compute='_compute_kpis', string='Allocated Usage Cost')
    period_maintenance_cost = fields.Monetary(
        compute='_compute_kpis', string='Maintenance & Repair'
    )
    period_rental_cost = fields.Monetary(compute='_compute_kpis', string='Rental Cost')
    period_other_cost = fields.Monetary(compute='_compute_kpis', string='Fuel, Transport & Other')
    cost_per_hour = fields.Monetary(compute='_compute_kpis', string='Cost per Hour')
    utilization_percent = fields.Float(
        compute='_compute_kpis',
        string='Utilization (%)',
        help=(
            'Operating hours compared to 8 hours per day for every '
            'equipment available or on site.'
        ),
    )
    cost_html = fields.Html(compute='_compute_kpis', sanitize=False, string='Cost Breakdown')
    type_html = fields.Html(compute='_compute_kpis', sanitize=False, string='By Type')
    location_html = fields.Html(compute='_compute_kpis', sanitize=False, string='By Location')
    top_html = fields.Html(compute='_compute_kpis', sanitize=False, string='Highest Costs')
    alert_html = fields.Html(compute='_compute_kpis', sanitize=False, string='Alerts')

    @api.depends('company_id')
    def _compute_display_name(self):
        for dashboard in self:
            dashboard.display_name = _('Machines & Equipment Dashboard')

    def _equipment_domain(self):
        self.ensure_one()
        domain = [('company_id', '=', self.company_id.id), ('is_vehicle', '=', False)]
        if self.project_id:
            domain.append(('current_project_id', '=', self.project_id.id))
        if self.category:
            domain.append(('category', '=', self.category))
        if self.ownership:
            domain.append(('ownership', '=', self.ownership))
        return domain

    def _get_equipment(self):
        return self.env['construction.equipment'].sudo().search(self._equipment_domain())

    def _period_domain(self, equipment):
        self.ensure_one()
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('equipment_id', 'in', equipment.ids),
        ]
        if self.project_id:
            domain.append(('project_id', '=', self.project_id.id))
        return domain

    def _get_period_records(self, equipment):
        """Usage logs and recorded expenses of the period for the equipment (any location
        when no project filter: the equipment may have worked on several sites in the
        period)."""
        self.ensure_one()
        all_equipment = equipment
        if self.project_id:
            all_equipment = (
                self.env['construction.equipment']
                .sudo()
                .search([d for d in self._equipment_domain() if d[0] != 'current_project_id'])
            )
        usages = (
            self.env['construction.equipment.usage']
            .sudo()
            .search(self._period_domain(all_equipment))
        )
        expenses = (
            self.env['construction.equipment.expense']
            .sudo()
            .search(self._period_domain(all_equipment) + [('state', 'in', ('submitted', 'billed'))])
        )
        return (usages, expenses)

    @api.depends('company_id', 'date_from', 'date_to', 'project_id', 'category', 'ownership')
    def _compute_kpis(self):
        movement_model = self.env['construction.equipment.movement'].sudo()
        request_model = self.env['construction.equipment.request'].sudo()
        expense_model = self.env['construction.equipment.expense'].sudo()
        usage_model = self.env['construction.equipment.usage'].sudo()
        today = fields.Date.context_today(self)
        for dashboard in self:
            if not dashboard.company_id or not dashboard.date_from or (not dashboard.date_to):
                call_method(dashboard, '_set_empty')
                continue
            company = dashboard.company_id
            equipment = call_method(dashboard, '_get_equipment')
            usages, expenses = call_method(dashboard, '_get_period_records', equipment)
            dashboard.total_count = len(equipment)
            dashboard.owned_count = len(equipment.filtered(lambda e: e.ownership == 'owned'))
            dashboard.rented_count = len(equipment.filtered(lambda e: e.ownership == 'rented'))
            in_transit = call_method(dashboard, '_get_in_transit', equipment)
            dashboard.available_count = len(
                equipment.filtered(lambda e: e.state == 'available') - in_transit
            )
            dashboard.on_site_count = len(equipment.filtered(lambda e: e.state == 'in_use'))
            dashboard.maintenance_count = len(
                equipment.filtered(lambda e: e.state == 'maintenance')
            )
            dashboard.inactive_count = len(equipment.filtered(lambda e: e.state == 'inactive'))
            transit_domain = [
                ('state', '=', 'in_transit'),
                ('company_id', '=', company.id),
                ('equipment_id.is_vehicle', '=', False),
            ]
            if dashboard.project_id:
                transit_domain += [
                    '|',
                    ('to_project_id', '=', dashboard.project_id.id),
                    ('from_project_id', '=', dashboard.project_id.id),
                ]
            dashboard.in_transit_count = movement_model.search_count(transit_domain)
            request_domain = [('company_id', '=', company.id)]
            if dashboard.project_id:
                request_domain.append(('project_id', '=', dashboard.project_id.id))
            dashboard.pending_request_count = request_model.search_count(
                request_domain + [('state', '=', 'submitted')]
            )
            dashboard.approval_request_count = request_model.search_count(
                request_domain + [('state', '=', 'to_approve')]
            )
            dashboard.pending_expense_count = expense_model.search_count(
                [
                    ('state', '=', 'submitted'),
                    ('company_id', '=', company.id),
                    ('equipment_id.is_vehicle', '=', False),
                ]
            )
            dashboard.draft_usage_count = usage_model.search_count(
                [
                    ('state', '=', 'draft'),
                    ('company_id', '=', company.id),
                    ('equipment_id.is_vehicle', '=', False),
                ]
            )
            ending = call_method(dashboard, '_get_rentals_ending', equipment, today)
            dashboard.rental_alert_count = len(ending)
            _set_period_costs(dashboard, equipment, usages, expenses)
            dashboard.type_html = call_method(
                dashboard, '_render_types', equipment, usages, expenses
            )
            dashboard.location_html = call_method(
                dashboard, '_render_locations', equipment, usages, expenses
            )
            dashboard.top_html = call_method(dashboard, '_render_top', usages, expenses)
            dashboard.alert_html = call_method(
                dashboard, '_render_alerts', equipment, ending, today
            )

    def _set_empty(self):
        for name, field in self._fields.items():
            if field.compute == '_compute_kpis':
                self[name] = False if field.type == 'html' else 0

    def _get_in_transit(self, equipment):
        return (
            self.env['construction.equipment.movement']
            .sudo()
            .search([('state', '=', 'in_transit'), ('equipment_id', 'in', equipment.ids)])
            .equipment_id
        )

    def _get_rentals_ending(self, equipment, today):
        limit = today + timedelta(days=RENTAL_ALERT_DAYS)
        return equipment.filtered(
            lambda e: e.ownership == 'rented'
            and e.rental_end_date
            and (e.rental_end_date <= limit)
            and (e.state != 'inactive')
        )

    def _render_costs(self, costs):
        labels = self._cost_labels()
        return self._render_cost_bar(
            [(labels[key], costs[key], css) for (key, _label, css) in COST_GROUPS]
        )

    def _cost_labels(self):
        return {
            'usage': _('Operation (hours)'),
            'fuel': _('Fuel & Oil'),
            'maintenance': _('Maintenance & Repair'),
            'rental': _('Rental'),
            'other': _('Transport & Other'),
        }

    def _cost_by(self, records, key):
        result = {}
        for record in records:
            amount = (
                record.total_cost
                if MODEL_NAME(record) == 'construction.equipment.usage'
                else record.amount
            )
            if MODEL_NAME(record) == 'construction.equipment.usage' and record.state != 'posted':
                amount = 0.0
            result[key(record)] = result.get(key(record), 0.0) + amount
        return result

    def _render_types(self, equipment, usages, expenses):
        if not equipment:
            return self._html_empty(_('No equipment matches the filters.'))
        labels = dict(
            call_method(
                self.env['construction.equipment']._fields['category'],
                '_description_selection',
                self.env,
            )
        )
        hours = {}
        for usage in usages:
            hours[usage.equipment_id.category] = (
                hours.get(usage.equipment_id.category, 0.0) + usage.hours
            )
        cost = self._cost_by(usages, lambda r: r.equipment_id.category)
        for category, amount in self._cost_by(expenses, lambda r: r.equipment_id.category).items():
            cost[category] = cost.get(category, 0.0) + amount
        rows = []
        in_transit = self._get_in_transit(equipment)
        for category in sorted(set(equipment.mapped('category')), key=lambda c: labels.get(c, '')):
            items = equipment.filtered(lambda e, c=category: e.category == c)
            rows.append(
                [
                    escape(labels.get(category, category or '')),
                    len(items),
                    len(items.filtered(lambda e: e.state == 'available') - in_transit),
                    len(items.filtered(lambda e: e.state == 'in_use')),
                    len(items.filtered(lambda e: e.state in ('maintenance', 'inactive'))),
                    self._num(hours.get(category, 0.0)),
                    self._money(cost.get(category, 0.0)),
                ]
            )
        footer = [
            _('Total'),
            len(equipment),
            len(equipment.filtered(lambda e: e.state == 'available') - in_transit),
            len(equipment.filtered(lambda e: e.state == 'in_use')),
            len(equipment.filtered(lambda e: e.state in ('maintenance', 'inactive'))),
            self._num(sum(hours.values())),
            self._money(sum(cost.values())),
        ]
        return self._html_table(
            [
                _('Type'),
                _('Count'),
                _('In Yard'),
                _('On Site'),
                _('Stopped'),
                _('Hours'),
                _('Cost'),
            ],
            rows,
            footer=footer,
        )

    def _render_locations(self, equipment, usages, expenses):
        groups = {}
        for item in equipment:
            groups.setdefault(item.current_project_id, self.env['construction.equipment'])
            groups[item.current_project_id] |= item
        hours = {}
        for usage in usages:
            hours[usage.project_id] = hours.get(usage.project_id, 0.0) + usage.hours
        cost = self._cost_by(usages, lambda r: r.project_id)
        for project, amount in self._cost_by(expenses, lambda r: r.project_id).items():
            cost[project] = cost.get(project, 0.0) + amount
        for project in set(hours) | set(cost):
            groups.setdefault(project, self.env['construction.equipment'])
        if not groups:
            return self._html_empty(_('No equipment matches the filters.'))
        in_transit = self._get_in_transit(equipment)
        rows = []
        for project, items in sorted(
            groups.items(), key=lambda kv: (bool(kv[0]), kv[0].display_name or '')
        ):
            rows.append(self._location_row(project, items, hours, cost, in_transit))
        return self._render_location_table(equipment, hours, cost, rows)

    def _render_top(self, usages, expenses):
        cost = self._cost_by(usages, lambda r: r.equipment_id)
        for item, amount in self._cost_by(expenses, lambda r: r.equipment_id).items():
            cost[item] = cost.get(item, 0.0) + amount
        hours = {}
        for usage in usages:
            hours[usage.equipment_id] = hours.get(usage.equipment_id, 0.0) + usage.hours
        top = sorted(
            ((item, amount) for (item, amount) in cost.items() if amount), key=lambda kv: -kv[1]
        )[:5]
        if not top:
            return self._html_empty(_('No cost recorded in this period.'))
        highest = top[0][1]
        rows = []
        for item, amount in top:
            progress_bar = (
                Markup(
                    (
                        '<div class="progress mt-1" style="height: 4px"><div '
                        'class="progress-bar bg-danger" style="width: '
                        '%s%%"></div></div>'
                    )
                )
                % f'{amount / highest * 100.0:.1f}'
            )
            rows.append(
                [
                    Markup('%s%s') % (item.display_name, progress_bar),
                    self._num(hours.get(item, 0.0)),
                    self._money(amount),
                ]
            )
        return self._html_table([_('Equipment'), _('Hours'), _('Cost')], rows)

    def _render_alerts(self, equipment, ending, today):
        items = []
        for item in ending.sorted('rental_end_date'):
            late = item.rental_end_date < today
            items.append(
                (
                    'text-danger' if late else 'text-warning',
                    'fa-calendar-times-o',
                    (
                        _(
                            '%(equipment)s: rental ended on %(date)s',
                            equipment=item.display_name,
                            date=format_date(self.env, item.rental_end_date),
                        )
                        if late
                        else _(
                            '%(equipment)s: rental ends on %(date)s',
                            equipment=item.display_name,
                            date=format_date(self.env, item.rental_end_date),
                        )
                    ),
                )
            )
        for item in equipment.filtered(lambda e: e.state == 'maintenance'):
            items.append(
                ('text-warning', 'fa-wrench', _('%s is under maintenance', item.display_name))
            )
        for item in equipment.filtered(lambda e: e.state == 'inactive'):
            items.append(('text-muted', 'fa-ban', _('%s is out of service', item.display_name)))
        if 'asset_id' in equipment._fields:
            no_asset = equipment.filtered(lambda e: e.ownership == 'owned' and (not e.asset_id))
            if no_asset:
                items.append(
                    (
                        'text-danger',
                        'fa-building',
                        _('%s company owned equipment not linked to a fixed asset', len(no_asset)),
                    )
                )
        if self.approval_request_count:
            items.append(
                (
                    'text-danger',
                    'fa-gavel',
                    _(
                        '%s equipment request(s) exceed the BOQ and wait for Senior Management',
                        self.approval_request_count,
                    ),
                )
            )
        if self.draft_usage_count:
            items.append(
                (
                    'text-info',
                    'fa-clock-o',
                    _('%s usage log(s) are not posted yet', self.draft_usage_count),
                )
            )
        return self._render_alert_list(items)

    def _open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Machines & Equipment Dashboard'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_refresh(self):
        """Action refresh."""
        self.invalidate_recordset()
        return self._open()

    @api.model
    def action_open_dashboard(self):
        """Action open dashboard."""
        return call_method(self.create({}), '_open')

    def action_open_equipment(self):
        """Action open equipment."""
        self.ensure_one()
        domain = self._equipment_domain()
        state = self.env.context.get('dashboard_state')
        ownership = self.env.context.get('dashboard_ownership')
        if state:
            domain.append(('state', '=', state))
        if ownership:
            domain.append(('ownership', '=', ownership))
        if self.env.context.get('dashboard_rental_alert'):
            domain.append(
                (
                    'id',
                    'in',
                    self._get_rentals_ending(
                        self._get_equipment(), fields.Date.context_today(self)
                    ).ids,
                )
            )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Machines & Equipment'),
            'res_model': 'construction.equipment',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
            'context': {'default_category': self.category or 'equipment'},
        }

    def action_open_requests(self):
        """Action open requests."""
        self.ensure_one()
        state = self.env.context.get('dashboard_request_state', 'submitted')
        domain = [('state', '=', state), ('company_id', '=', self.company_id.id)]
        if self.project_id:
            domain.append(('project_id', '=', self.project_id.id))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Equipment Requests'),
            'res_model': 'construction.equipment.request',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
        }

    def action_open_movements(self):
        """Action open movements."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Equipment in Transit'),
            'res_model': 'construction.equipment.movement',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [
                ('state', '=', 'in_transit'),
                ('company_id', '=', self.company_id.id),
                ('equipment_id.is_vehicle', '=', False),
            ],
        }

    def action_open_expenses(self):
        """Action open expenses."""
        self.ensure_one()
        domain = [('company_id', '=', self.company_id.id), ('equipment_id.is_vehicle', '=', False)]
        if self.env.context.get('dashboard_period'):
            domain += [
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('state', 'in', ('submitted', 'billed')),
            ]
            if self.project_id:
                domain.append(('project_id', '=', self.project_id.id))
        else:
            domain.append(('state', '=', 'submitted'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Equipment Expenses'),
            'res_model': 'construction.equipment.expense',
            'view_mode': 'list,pivot,form',
            'views': [(False, 'list'), (False, 'pivot'), (False, 'form')],
            'domain': domain,
        }

    def action_open_usage(self):
        """Action open usage."""
        self.ensure_one()
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
            ('equipment_id.is_vehicle', '=', False),
        ]
        if self.env.context.get('dashboard_draft'):
            domain = [
                ('state', '=', 'draft'),
                ('company_id', '=', self.company_id.id),
                ('equipment_id.is_vehicle', '=', False),
            ]
        elif self.project_id:
            domain.append(('project_id', '=', self.project_id.id))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Equipment Utilization'),
            'res_model': 'construction.equipment.usage',
            'view_mode': 'pivot,list,form',
            'views': [(False, 'pivot'), (False, 'list'), (False, 'form')],
            'domain': domain,
        }

    def _location_badge(self, item, in_transit):
        """Render one escaped equipment badge with its original state styling."""
        state_css = {
            'available': 'text-bg-success',
            'in_use': 'text-bg-primary',
            'maintenance': 'text-bg-warning',
            'inactive': 'text-bg-secondary',
        }
        if item in in_transit:
            return Markup(
                (
                    '<span class="badge rounded-pill text-bg-info fw-normal" '
                    'title="%s"><i class="fa fa-truck me-1"></i>%s</span>'
                )
            ) % (_('In transit'), item.display_name)
        return Markup('<span class="badge rounded-pill %s fw-normal">%s</span>') % (
            state_css.get(item.state, 'text-bg-light'),
            item.display_name,
        )

    def _location_row(self, project, items, hours, cost, in_transit):
        """Render one location row without changing its values or HTML escaping."""
        badges = Markup(' ').join(
            (self._location_badge(item, in_transit) for item in items)
        ) or Markup('<span class="text-muted small">%s</span>') % _('(left the site)')
        location = (
            Markup('<i class="fa fa-home me-1 text-muted"></i>%s') % _('Main Yard')
            if not project
            else Markup('<i class="fa fa-map-marker me-1 text-muted"></i>%s') % project.display_name
        )
        return [
            location,
            len(items),
            badges,
            self._num(hours.get(project, 0.0)),
            self._money(cost.get(project, 0.0)),
        ]

    def _render_location_table(self, equipment, hours, cost, rows):
        """Render the location table with the original column classes and totals."""
        headers = [_('Location'), _('Count'), _('Equipment'), _('Hours'), _('Cost')]
        head = Markup('').join(
            (
                Markup('<th class="%s">%s</th>') % (css, header)
                for (css, header) in zip(('', 'text-end', '', 'text-end', 'text-end'), headers)
            )
        )
        body = Markup('').join(
            (
                Markup(
                    (
                        '<tr><td class="text-nowrap">%s</td><td '
                        'class="text-end">%s</td><td>%s</td><td class="text-end '
                        'text-nowrap">%s</td><td class="text-end '
                        'text-nowrap">%s</td></tr>'
                    )
                )
                % tuple(row)
                for row in rows
            )
        )
        foot = Markup(
            (
                '<tfoot><tr class="fw-bold"><td>%s</td><td '
                'class="text-end">%s</td><td></td><td class="text-end '
                'text-nowrap">%s</td><td class="text-end '
                'text-nowrap">%s</td></tr></tfoot>'
            )
        ) % (
            _('Total'),
            len(equipment),
            self._num(sum(hours.values())),
            self._money(sum(cost.values())),
        )
        return self._html_table_shell(head, body, foot)


def _set_period_costs(dashboard, equipment, usages, expenses):
    """Set the original operating cost and utilization figures for one dashboard."""
    costs = dict.fromkeys([key for (key, _label, _css) in COST_GROUPS], 0.0)
    costs['usage'] = sum(usages.filtered(lambda u: u.state == 'posted').mapped('total_cost'))
    for expense in expenses:
        costs[EXPENSE_GROUP.get(expense.expense_type, 'other')] += expense.amount
    dashboard.period_hours = sum(usages.mapped('hours'))
    dashboard.period_usage_cost = costs['usage']
    dashboard.period_maintenance_cost = costs['maintenance']
    dashboard.period_rental_cost = costs['rental']
    dashboard.period_other_cost = costs['fuel'] + costs['other']
    dashboard.period_cost = sum(costs.values())
    dashboard.cost_per_hour = (
        dashboard.period_cost / dashboard.period_hours if dashboard.period_hours else 0.0
    )
    active = len(equipment.filtered(lambda e: e.state in ('available', 'in_use')))
    days = max((dashboard.date_to - dashboard.date_from).days + 1, 0)
    capacity = active * days * 8.0
    dashboard.utilization_percent = (
        min(dashboard.period_hours / capacity * 100.0, 100.0) if capacity else 0.0
    )
    dashboard.cost_html = call_method(dashboard, '_render_costs', costs)
