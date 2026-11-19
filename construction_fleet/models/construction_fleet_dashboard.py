"""Construction fleet construction fleet dashboard support."""

from datetime import timedelta
from markupsafe import Markup, escape
from odoo import _, api, fields, models
from odoo.tools.misc import format_date
from odoo.addons.construction_management.models.construction_equipment import (
    EQUIPMENT_CATEGORIES,
    VEHICLE_CATEGORIES,
)
from odoo.addons.construction_equipment.models.runtime import call_method

FLEET_CATEGORIES = [
    (key, label) for (key, label) in EQUIPMENT_CATEGORIES if key in VEHICLE_CATEGORIES
]
DOCUMENT_ALERT_DAYS = 30
RENTAL_ALERT_DAYS = 7
SHEET_COST_STATES = ('submitted', 'done')
EXPENSE_KIND_CSS = {
    'freight': 'bg-info',
    'tips': 'bg-success',
    'tolls': 'bg-success opacity-50',
    'loading': 'bg-dark',
    'other': 'bg-dark opacity-50',
}


class ConstructionFleetDashboard(models.TransientModel):
    """Dashboard of the vehicles and drivers. Every figure is computed live from the
    filters. Costs: trips and other expenses of the custody sheets submitted or
    settled, and the expenses recorded on the vehicles (fuel, maintenance,
    rental...)."""

    _name = 'construction.fleet.dashboard'
    _inherit = ['construction.dashboard.mixin']
    _description = 'Fleet Dashboard'
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
        help='Trips and costs charged to this project, vehicles currently on its site.',
    )
    category = fields.Selection(FLEET_CATEGORIES, string='Vehicle Type')
    ownership = fields.Selection(
        [('owned', 'Company Owned'), ('rented', 'Rented')], string='Ownership'
    )
    driver_id = fields.Many2one(
        'construction.driver', string='Driver', domain="[('company_id', '=', company_id)]"
    )
    vehicle_count = fields.Integer(compute='_compute_kpis', string='All Vehicles')
    available_count = fields.Integer(compute='_compute_kpis', string='Available in Yard')
    on_site_count = fields.Integer(compute='_compute_kpis', string='On Project Sites')
    in_transit_count = fields.Integer(compute='_compute_kpis', string='In Transit')
    maintenance_count = fields.Integer(compute='_compute_kpis', string='Under Maintenance')
    inactive_count = fields.Integer(compute='_compute_kpis', string='Out of Service')
    driver_count = fields.Integer(compute='_compute_kpis', string='Active Drivers')
    license_alert_count = fields.Integer(compute='_compute_kpis', string='Licenses Expiring')
    document_alert_count = fields.Integer(compute='_compute_kpis', string='Documents Expiring')
    draft_sheet_count = fields.Integer(compute='_compute_kpis', string='Sheets in Draft')
    submitted_sheet_count = fields.Integer(compute='_compute_kpis', string='Sheets to Settle')
    rental_alert_count = fields.Integer(compute='_compute_kpis', string='Rentals Ending')
    trip_count = fields.Integer(compute='_compute_kpis', string='Trips')
    trips_value = fields.Monetary(compute='_compute_kpis', string='Trips Value')
    other_expenses = fields.Monetary(compute='_compute_kpis', string='Other Expenses')
    vehicle_expenses = fields.Monetary(compute='_compute_kpis', string='Vehicle Expenses')
    period_cost = fields.Monetary(compute='_compute_kpis', string='Total Cost')
    cost_per_trip = fields.Monetary(compute='_compute_kpis', string='Cost per Trip')
    cost_html = fields.Html(compute='_compute_kpis', sanitize=False, string='Cost Breakdown')
    type_html = fields.Html(compute='_compute_kpis', sanitize=False, string='By Trip Type')
    project_html = fields.Html(compute='_compute_kpis', sanitize=False, string='By Project')
    top_html = fields.Html(compute='_compute_kpis', sanitize=False, string='Highest Costs')
    alert_html = fields.Html(compute='_compute_kpis', sanitize=False, string='Alerts')

    @api.depends('company_id')
    def _compute_display_name(self):
        for dashboard in self:
            dashboard.display_name = _('Fleet Dashboard')

    def _vehicle_domain(self, with_location=True):
        self.ensure_one()
        domain = [('company_id', '=', self.company_id.id), ('is_vehicle', '=', True)]
        if with_location and self.project_id:
            domain.append(('current_project_id', '=', self.project_id.id))
        if self.category:
            domain.append(('category', '=', self.category))
        if self.ownership:
            domain.append(('ownership', '=', self.ownership))
        if self.driver_id:
            domain.append(('driver_id', '=', self.driver_id.id))
        return domain

    def _get_vehicles(self, with_location=True):
        return self.env['construction.equipment'].sudo().search(self._vehicle_domain(with_location))

    def _get_in_transit(self, vehicles):
        return (
            self.env['construction.equipment.movement']
            .sudo()
            .search([('state', '=', 'in_transit'), ('equipment_id', 'in', vehicles.ids)])
            .equipment_id
        )

    def _get_period_records(self):
        """Trips, other sheet expenses and vehicle expenses of the period (any current
        location: a vehicle may have worked on several sites)."""
        self.ensure_one()
        vehicles = self._get_vehicles(with_location=False)
        sheet_domain = [
            ('sheet_id.vehicle_id', 'in', vehicles.ids),
            ('sheet_id.state', 'in', SHEET_COST_STATES),
        ]
        if self.driver_id:
            sheet_domain.append(('sheet_id.driver_id', '=', self.driver_id.id))
        period = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        trip_domain = sheet_domain + period
        if self.project_id:
            trip_domain.append(('project_id', '=', self.project_id.id))
        trips = self.env['construction.vehicle.sheet.trip'].sudo().search(trip_domain)
        sheet_expenses = (
            self.env['construction.vehicle.sheet.expense']
            .sudo()
            .search(sheet_domain)
            .filtered(lambda e: self.date_from <= (e.date or e.sheet_id.date_to) <= self.date_to)
        )
        if self.project_id:
            sheet_expenses = sheet_expenses.filtered(
                lambda e: not e.distribute
                and e.project_id == self.project_id
                or (e.distribute and self.project_id in e.sheet_id.trip_ids.project_id)
            )
        expense_domain = [
            ('equipment_id', 'in', vehicles.ids),
            ('state', 'in', ('submitted', 'billed')),
        ] + period
        if self.project_id:
            expense_domain.append(('project_id', '=', self.project_id.id))
        vehicle_expenses = self.env['construction.equipment.expense'].sudo().search(expense_domain)
        return (trips, sheet_expenses, vehicle_expenses)

    @api.depends(
        'company_id', 'date_from', 'date_to', 'project_id', 'category', 'ownership', 'driver_id'
    )
    def _compute_kpis(self):
        driver_model = self.env['construction.driver'].sudo()
        document_model = self.env['construction.driver.document'].sudo()
        sheet_model = self.env['construction.vehicle.sheet'].sudo()
        today = fields.Date.context_today(self)
        for dashboard in self:
            if not dashboard.company_id or not dashboard.date_from or (not dashboard.date_to):
                call_method(dashboard, '_set_empty')
                continue
            company = dashboard.company_id
            vehicles = call_method(dashboard, '_get_vehicles')
            in_transit = call_method(dashboard, '_get_in_transit', vehicles)
            dashboard.vehicle_count = len(vehicles)
            dashboard.available_count = len(
                vehicles.filtered(lambda v: v.state == 'available') - in_transit
            )
            dashboard.on_site_count = len(vehicles.filtered(lambda v: v.state == 'in_use'))
            dashboard.in_transit_count = len(in_transit)
            dashboard.maintenance_count = len(vehicles.filtered(lambda v: v.state == 'maintenance'))
            dashboard.inactive_count = len(vehicles.filtered(lambda v: v.state == 'inactive'))
            limit = today + timedelta(days=DOCUMENT_ALERT_DAYS)
            drivers = driver_model.search(
                [('company_id', '=', company.id), ('employment_status', '!=', 'terminated')]
            )
            dashboard.driver_count = len(
                drivers.filtered(lambda d: d.employment_status in ('active', 'external'))
            )
            licenses = drivers.filtered(
                lambda d, limit=limit: d.license_expiry and d.license_expiry <= limit
            )
            documents = document_model.search(
                [
                    ('driver_id', 'in', drivers.ids),
                    ('expiry_date', '!=', False),
                    ('expiry_date', '<=', limit),
                ]
            )
            dashboard.license_alert_count = len(licenses)
            dashboard.document_alert_count = len(documents)
            sheet_domain = [('company_id', '=', company.id)]
            if dashboard.driver_id:
                sheet_domain.append(('driver_id', '=', dashboard.driver_id.id))
            dashboard.draft_sheet_count = sheet_model.search_count(
                sheet_domain + [('state', '=', 'draft')]
            )
            dashboard.submitted_sheet_count = sheet_model.search_count(
                sheet_domain + [('state', '=', 'submitted')]
            )
            ending = call_method(dashboard, '_get_rentals_ending', vehicles, today)
            dashboard.rental_alert_count = len(ending)
            _set_period_costs(dashboard)
            dashboard.alert_html = call_method(
                dashboard, '_render_fleet_alerts', vehicles, licenses, documents, ending, today
            )

    def _set_empty(self):
        for name, field in self._fields.items():
            if field.compute == '_compute_kpis':
                self[name] = False if field.type == 'html' else 0

    def _get_rentals_ending(self, vehicles, today):
        limit = today + timedelta(days=RENTAL_ALERT_DAYS)
        return vehicles.filtered(
            lambda v, limit=limit: v.ownership == 'rented'
            and v.rental_end_date
            and (v.rental_end_date <= limit)
            and (v.state != 'inactive')
        )

    def _selection_labels(self, model, field):
        return dict(call_method(self.env[model]._fields[field], '_description_selection', self.env))

    def _render_fleet_costs(self, trips, sheet_expenses, vehicle_expenses):
        kinds = self._selection_labels('construction.vehicle.sheet.expense', 'expense_kind')
        items = [(_('Trips'), sum(trips.mapped('amount')), 'bg-primary')]
        for kind, label in kinds.items():
            amount = sum(
                sheet_expenses.filtered(lambda e, k=kind: e.expense_kind == k).mapped('amount')
            )
            if amount:
                items.append((label, amount, EXPENSE_KIND_CSS.get(kind, 'bg-secondary')))
        groups = [
            (_('Fuel & Oil'), ('fuel', 'oil'), 'bg-warning'),
            (_('Maintenance & Repair'), ('maintenance', 'repair'), 'bg-danger'),
            (_('Rental'), ('rental',), 'text-bg-danger opacity-50'),
        ]
        grouped = set()
        for label, keys, css in groups:
            grouped.update(keys)
            amount = sum(
                vehicle_expenses.filtered(lambda e, k=keys: e.expense_type in k).mapped('amount')
            )
            if amount:
                items.append((label, amount, css))
        rest = sum(
            vehicle_expenses.filtered(lambda e: e.expense_type not in grouped).mapped('amount')
        )
        if rest:
            items.append((_('Other Vehicle Expenses'), rest, 'bg-secondary'))
        return self._render_cost_bar(items)

    def _render_trip_types(self, trips):
        if not trips:
            return self._html_empty(_('No trip recorded in this period.'))
        rows = []
        for trip_type in trips.transport_type_id.sorted('sequence'):
            items = trips.filtered(lambda t, tt=trip_type: t.transport_type_id == tt)
            quantity = sum(items.mapped('quantity'))
            total = sum(items.mapped('total_cost'))
            unit = (
                Markup(' <span class="text-muted small">%s</span>') % trip_type.uom_id.name
                if trip_type.uom_id
                else Markup('')
            )
            rows.append(
                [
                    escape(trip_type.name),
                    len(items),
                    Markup('%s%s') % (self._num(quantity, 2), unit),
                    self._money(sum(items.mapped('amount'))),
                    self._money(sum(items.mapped('allocated_amount'))),
                    self._money(total),
                    self._money(total / quantity) if quantity else '-',
                ]
            )
        footer = [
            _('Total'),
            len(trips),
            '',
            self._money(sum(trips.mapped('amount'))),
            self._money(sum(trips.mapped('allocated_amount'))),
            self._money(sum(trips.mapped('total_cost'))),
            '',
        ]
        return self._html_table(
            [
                _('Trip Type'),
                _('Trips'),
                _('Quantity'),
                _('Value'),
                _('Distributed Expenses'),
                _('Total Cost'),
                _('Cost per Unit'),
            ],
            rows,
            footer=footer,
        )

    def _project_costs(self, trips, sheet_expenses, vehicle_expenses):
        costs = {}
        counts = {}
        for trip in trips:
            costs[trip.project_id] = costs.get(trip.project_id, 0.0) + trip.total_cost
            counts[trip.project_id] = counts.get(trip.project_id, 0) + 1
        for expense in sheet_expenses.filtered(lambda e: not e.distribute):
            costs[expense.project_id] = costs.get(expense.project_id, 0.0) + expense.amount
        for expense in vehicle_expenses:
            costs[expense.project_id] = costs.get(expense.project_id, 0.0) + expense.amount
        return (costs, counts)

    def _render_projects(self, trips, sheet_expenses, vehicle_expenses):
        costs, counts = self._project_costs(trips, sheet_expenses, vehicle_expenses)
        if not costs:
            return self._html_empty(_('No cost recorded in this period.'))
        vehicles_by_project = {}
        for trip in trips:
            vehicles_by_project.setdefault(trip.project_id, set()).add(trip.sheet_id.vehicle_id)
        for expense in vehicle_expenses:
            vehicles_by_project.setdefault(expense.project_id, set()).add(expense.equipment_id)
        rows = []
        for project, amount in sorted(costs.items(), key=lambda kv: -kv[1]):
            rows.append(self._project_row(project, amount, counts, vehicles_by_project))
        head = Markup(
            '<th>%s</th><th class="text-end">%s</th><th>%s</th><th class="text-end">%s</th>'
        ) % (_('Project'), _('Trips'), _('Vehicles'), _('Cost'))
        body = Markup('').join(
            (
                Markup(
                    (
                        '<tr><td class="text-nowrap">%s</td><td '
                        'class="text-end">%s</td><td>%s</td><td class="text-end '
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
                'text-nowrap">%s</td></tr></tfoot>'
            )
        ) % (_('Total'), len(trips), self._money(sum(costs.values())))
        return self._html_table_shell(head, body, foot)

    def _render_top(self, trips, sheet_expenses, vehicle_expenses):
        costs = {}
        counts = {}
        for trip in trips:
            vehicle = trip.sheet_id.vehicle_id
            costs[vehicle] = costs.get(vehicle, 0.0) + trip.total_cost
            counts[vehicle] = counts.get(vehicle, 0) + 1
        for expense in sheet_expenses.filtered(lambda e: not e.distribute):
            costs[expense.sheet_id.vehicle_id] = (
                costs.get(expense.sheet_id.vehicle_id, 0.0) + expense.amount
            )
        for expense in vehicle_expenses:
            costs[expense.equipment_id] = costs.get(expense.equipment_id, 0.0) + expense.amount
        top = sorted(((v, a) for (v, a) in costs.items() if a), key=lambda kv: -kv[1])[:5]
        if not top:
            return self._html_empty(_('No cost recorded in this period.'))
        highest = top[0][1]
        rows = []
        for vehicle, amount in top:
            rows.append(self._top_vehicle_row(vehicle, amount, highest, counts))
        return self._html_table([_('Vehicle'), _('Trips'), _('Cost')], rows)

    def _render_fleet_alerts(self, vehicles, licenses, documents, ending, today):
        items = []
        for driver in licenses.sorted('license_expiry'):
            expired = driver.license_expiry < today
            items.append(
                (
                    'text-danger' if expired else 'text-warning',
                    'fa-id-card-o',
                    (
                        _(
                            '%(driver)s: driving license expired on %(date)s',
                            driver=driver.name,
                            date=format_date(self.env, driver.license_expiry),
                        )
                        if expired
                        else _(
                            '%(driver)s: driving license expires on %(date)s',
                            driver=driver.name,
                            date=format_date(self.env, driver.license_expiry),
                        )
                    ),
                )
            )
        doc_types = self._selection_labels('construction.driver.document', 'document_type')
        for document in documents.sorted('expiry_date'):
            expired = document.expiry_date < today
            items.append(
                (
                    'text-danger' if expired else 'text-warning',
                    'fa-file-o',
                    (
                        _(
                            '%(driver)s: %(document)s expired on %(date)s',
                            driver=document.driver_id.name,
                            document=doc_types.get(document.document_type, document.name or ''),
                            date=format_date(self.env, document.expiry_date),
                        )
                        if expired
                        else _(
                            '%(driver)s: %(document)s expires on %(date)s',
                            driver=document.driver_id.name,
                            document=doc_types.get(document.document_type, document.name or ''),
                            date=format_date(self.env, document.expiry_date),
                        )
                    ),
                )
            )
        for vehicle in ending.sorted('rental_end_date'):
            late = vehicle.rental_end_date < today
            items.append(
                (
                    'text-danger' if late else 'text-warning',
                    'fa-calendar-times-o',
                    (
                        _(
                            '%(vehicle)s: rental ended on %(date)s',
                            vehicle=vehicle.display_name,
                            date=format_date(self.env, vehicle.rental_end_date),
                        )
                        if late
                        else _(
                            '%(vehicle)s: rental ends on %(date)s',
                            vehicle=vehicle.display_name,
                            date=format_date(self.env, vehicle.rental_end_date),
                        )
                    ),
                )
            )
        for vehicle in vehicles.filtered(lambda v: v.state == 'maintenance'):
            items.append(
                ('text-warning', 'fa-wrench', _('%s is under maintenance', vehicle.display_name))
            )
        for vehicle in vehicles.filtered(
            lambda v: v.driver_id.employment_status in ('suspended', 'on_leave', 'terminated')
        ):
            items.append(
                (
                    'text-warning',
                    'fa-user-times',
                    _(
                        '%(vehicle)s: assigned driver %(driver)s is not available',
                        vehicle=vehicle.display_name,
                        driver=vehicle.driver_id.name,
                    ),
                )
            )
        if 'asset_id' in vehicles._fields:
            no_asset = vehicles.filtered(lambda v: v.ownership == 'owned' and (not v.asset_id))
            if no_asset:
                items.append(
                    (
                        'text-danger',
                        'fa-building',
                        _('%s company owned vehicle(s) not linked to a fixed asset', len(no_asset)),
                    )
                )
        if self.submitted_sheet_count:
            items.append(
                (
                    'text-info',
                    'fa-money',
                    _('%s custody sheet(s) wait for the settlement', self.submitted_sheet_count),
                )
            )
        return self._render_alert_list(items)

    def _open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fleet Dashboard'),
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

    def action_open_vehicles(self):
        """Action open vehicles."""
        self.ensure_one()
        domain = self._vehicle_domain()
        state = self.env.context.get('dashboard_state')
        if state:
            domain.append(('state', '=', state))
        if self.env.context.get('dashboard_rental_alert'):
            domain.append(
                (
                    'id',
                    'in',
                    self._get_rentals_ending(
                        self._get_vehicles(), fields.Date.context_today(self)
                    ).ids,
                )
            )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vehicles'),
            'res_model': 'construction.equipment',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
            'context': {'default_category': self.category or 'truck_light'},
        }

    def action_open_movements(self):
        """Action open movements."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vehicles in Transit'),
            'res_model': 'construction.equipment.movement',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [
                ('state', '=', 'in_transit'),
                ('equipment_id', 'in', self._get_vehicles().ids),
            ],
        }

    def action_open_drivers(self):
        """Action open drivers."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=DOCUMENT_ALERT_DAYS)
        domain = [('company_id', '=', self.company_id.id)]
        alert = self.env.context.get('dashboard_alert')
        if alert == 'license':
            domain += [('license_expiry', '!=', False), ('license_expiry', '<=', limit)]
        elif alert == 'document':
            domain += [
                ('document_ids.expiry_date', '!=', False),
                ('document_ids.expiry_date', '<=', limit),
            ]
        else:
            domain.append(('employment_status', 'in', ('active', 'external')))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Drivers'),
            'res_model': 'construction.driver',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
        }

    def action_open_sheets(self):
        """Action open sheets."""
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('state', '=', self.env.context.get('dashboard_sheet_state', 'draft')),
        ]
        if self.driver_id:
            domain.append(('driver_id', '=', self.driver_id.id))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vehicle Custody Sheets'),
            'res_model': 'construction.vehicle.sheet',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
        }

    def action_open_trips(self):
        """Action open trips."""
        self.ensure_one()
        trips = self._get_period_records()[0]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Trips Analysis'),
            'res_model': 'construction.vehicle.sheet.trip',
            'view_mode': 'pivot,list',
            'views': [(False, 'pivot'), (False, 'list')],
            'domain': [('id', 'in', trips.ids)],
        }

    def _top_vehicle_row(self, vehicle, amount, highest, counts):
        """Render one top-vehicle row with its original escaped values."""
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
        driver = (
            Markup('<div class="text-muted small">%s</div>') % vehicle.driver_id.name
            if vehicle.driver_id
            else Markup('')
        )
        return [
            Markup('%s%s%s') % (vehicle.display_name, driver, progress_bar),
            counts.get(vehicle, 0),
            self._money(amount),
        ]

    def _project_row(self, project, amount, counts, vehicles_by_project):
        """Render the escaped project and vehicle labels for one cost row."""
        location = (
            Markup('<i class="fa fa-map-marker me-1 text-muted"></i>%s') % project.display_name
            if project
            else Markup('<i class="fa fa-home me-1 text-muted"></i>%s') % _('Main Yard')
        )
        badges = Markup(' ').join(
            (
                Markup('<span class="badge rounded-pill text-bg-primary fw-normal">%s</span>')
                % vehicle.display_name
                for vehicle in sorted(
                    vehicles_by_project.get(project, set()), key=lambda v: v.display_name or ''
                )
            )
        )
        return [location, counts.get(project, 0), badges, self._money(amount)]


def _set_period_costs(dashboard):
    """Set period totals and render their original dashboard sections."""
    trips, sheet_expenses, vehicle_expenses = call_method(dashboard, '_get_period_records')
    dashboard.trip_count = len(trips)
    dashboard.trips_value = sum(trips.mapped('amount'))
    dashboard.other_expenses = sum(sheet_expenses.mapped('amount'))
    dashboard.vehicle_expenses = sum(vehicle_expenses.mapped('amount'))
    dashboard.period_cost = (
        dashboard.trips_value + dashboard.other_expenses + dashboard.vehicle_expenses
    )
    dashboard.cost_per_trip = dashboard.period_cost / len(trips) if trips else 0.0
    dashboard.cost_html = call_method(
        dashboard, '_render_fleet_costs', trips, sheet_expenses, vehicle_expenses
    )
    dashboard.type_html = call_method(dashboard, '_render_trip_types', trips)
    dashboard.project_html = call_method(
        dashboard, '_render_projects', trips, sheet_expenses, vehicle_expenses
    )
    dashboard.top_html = call_method(
        dashboard, '_render_top', trips, sheet_expenses, vehicle_expenses
    )
