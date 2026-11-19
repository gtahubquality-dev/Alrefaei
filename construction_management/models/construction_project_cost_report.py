"""Construction project cost report for construction management."""

from markupsafe import Markup
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.tools import float_is_zero
from odoo.tools import format_amount
from odoo.tools import format_date

from .runtime import model_attribute


class ConstructionProjectCostReport(models.TransientModel):
    """Construction project cost report."""

    _name = 'construction.project.cost.report'
    _description = 'Project Cost & Revenue Report'

    project_id = fields.Many2one('construction.project', string='Project', required=True)
    company_id = fields.Many2one(related='project_id.company_id', string='Company')
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    report_html = fields.Html(compute='_compute_report_html', sanitize=False, string='Report')

    @api.depends('project_id')
    def _compute_display_name(self):
        for report in self:
            report.display_name = (
                _('Cost & Revenue - %s', report.project_id.display_name)
                if report.project_id
                else _('Project Cost & Revenue')
            )

    def _get_form_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Project Cost & Revenue'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [
                (
                    self.env.ref(
                        'construction_management.view_construction_project_cost_report_form'
                    ).id,
                    'form',
                )
            ],
            'target': 'current',
        }

    @api.depends('project_id', 'date_from', 'date_to')
    def _compute_report_html(self):
        for report in self:
            if not report.project_id:
                report.report_html = Markup('<p class="text-muted">%s</p>') % _('Select a project.')
                continue
            data = model_attribute(report.project_id, '_get_cost_revenue_data')(
                report.date_from, report.date_to
            )
            report.report_html = model_attribute(report, '_render_report')(data)

    def action_print(self):
        """Print."""
        self.ensure_one()
        return self.env.ref('construction_management.action_report_project_cost').report_action(
            self
        )

    def _amount(self, value, currency):
        return format_amount(self.env, value or 0.0, currency)

    def _cell(self, value, currency, css=''):
        if not isinstance(value, (int, float)):
            return Markup('<td class="%s">%s</td>') % (css, value)
        classes = 'text-end text-nowrap ' + css
        if value < 0 and not float_is_zero(value, precision_rounding=currency.rounding):
            classes += ' text-danger'
        return Markup('<td class="%s">%s</td>') % (classes, self._amount(value, currency))

    def _html_table(self, headers, rows, footer=None):
        head = Markup('').join(
            Markup('<th class="%s">%s</th>') % ('text-end' if index else '', label)
            for index, label in enumerate(headers)
        )
        body = Markup('').join(Markup('<tr>%s</tr>') % Markup('').join(row) for row in rows)
        foot = (
            Markup('<tfoot class="fw-bold"><tr>%s</tr></tfoot>') % Markup('').join(footer)
            if footer
            else ''
        )
        return Markup(
            '<table class="table table-sm table-striped o_construction_cost_table">'
            '<thead><tr>%s</tr></thead><tbody>%s</tbody>%s</table>'
        ) % (head, body, foot)

    def _render_report(self, data):
        currency = data['currency']
        types = dict(
            model_attribute(
                self.env['construction.boq.component']._fields['component_type'],
                '_description_selection',
            )(self.env)
        )
        types['other'] = _('Other Costs')
        project = data['project']
        period = _('All dates')
        if data['date_from'] or data['date_to']:
            period = (
                f"{format_date(self.env, data['date_from']) if data['date_from'] else '...'!s}"
                ' - '
                f"{format_date(self.env, data['date_to']) if data['date_to'] else '...'!s}"
            )
        parts = [Markup('<div class="o_construction_cost_report">')]
        parts.append(
            Markup('<h3>%s</h3><p class="text-muted">%s: %s</p>')
            % (project.display_name, _('Period'), period)
        )

        cards = [
            (_('Contract Value'), data['contract_amount'], ''),
            (_('Revenue (Invoiced)'), data['revenue'], 'text-primary'),
            (_('Actual Cost'), data['total_cost'], 'text-warning'),
            (
                _('Gross Profit'),
                data['profit'],
                'text-success' if data['profit'] >= 0 else 'text-danger',
            ),
        ]
        parts.append(Markup('<div class="row g-2 mb-3">'))
        for label, value, css in cards:
            parts.append(
                Markup(
                    '<div class="col-6 col-lg-3"><div class="border rounded p-3 h-100"><div'
                    ' class="text-muted small">%s</div><div class="fs-4 fw-bold'
                    ' %s">%s</div></div></div>'
                )
                % (label, css, self._amount(value, currency))
            )
        parts.append(Markup('</div>'))
        parts.append(
            Markup(
                '<p>%s: <b>%s</b> &#160;|&#160; %s: <b>%s</b> &#160;|&#160; %s: <b>%.1f%%</b> '
                '&#160;|&#160; %s: <b>%.1f%%</b></p>'
            )
            % (
                _('Estimated Cost (BOQ)'),
                self._amount(data['estimated_cost'], currency),
                _('Expected Profit'),
                self._amount(data['contract_amount'] - data['estimated_cost'], currency),
                _('Profit Margin'),
                data['margin'],
                _('Progress'),
                data['progress'],
            )
        )

        rows = []
        for key, label in types.items():
            est, act = data['estimated'].get(key, 0.0), data['actual'].get(key, 0.0)
            rows.append(
                [
                    Markup('<td>%s</td>') % label,
                    self._cell(est, currency),
                    self._cell(act, currency),
                    self._cell(est - act, currency),
                ]
            )
        parts.append(Markup('<h4>%s</h4>') % _('Costs by Type'))
        parts.append(
            self._html_table(
                [_('Cost Type'), _('Estimated (BOQ)'), _('Actual'), _('Variance')],
                rows,
                [
                    Markup('<td>%s</td>') % _('Total'),
                    self._cell(data['estimated_cost'], currency),
                    self._cell(data['total_cost'], currency),
                    self._cell(data['estimated_cost'] - data['total_cost'], currency),
                ],
            )
        )

        rows = []
        for values in data['items']:
            item = values['item']
            rows.append(
                [
                    Markup('<td>%s</td>') % item.display_name,
                    self._cell(values['contract'], currency),
                    self._cell(values['revenue'], currency),
                    self._cell(values['estimated_total'], currency),
                    self._cell(values['actual']['material'], currency),
                    self._cell(values['actual']['equipment'], currency),
                    self._cell(values['actual']['subcontract'], currency),
                    self._cell(values['actual']['labor'] + values['actual']['other'], currency),
                    self._cell(values['actual_total'], currency),
                    self._cell(values['revenue'] - values['actual_total'], currency),
                ]
            )
        unallocated_total = sum(data['unallocated'].values())
        if not float_is_zero(
            unallocated_total, precision_rounding=currency.rounding
        ) or not float_is_zero(data['unallocated_revenue'], precision_rounding=currency.rounding):
            un = data['unallocated']
            rows.append(
                [
                    Markup('<td class="fst-italic">%s</td>') % _('Not linked to a BOQ item'),
                    self._cell('', currency),
                    self._cell(data['unallocated_revenue'], currency),
                    self._cell('', currency),
                    self._cell(un['material'], currency),
                    self._cell(un['equipment'], currency),
                    self._cell(un['subcontract'], currency),
                    self._cell(un['labor'] + un['other'], currency),
                    self._cell(unallocated_total, currency),
                    self._cell(data['unallocated_revenue'] - unallocated_total, currency),
                ]
            )
        parts.append(Markup('<h4>%s</h4>') % _('Revenue & Costs by BOQ Item'))
        parts.append(
            self._html_table(
                [
                    _('BOQ Item'),
                    _('Contract Value'),
                    _('Revenue'),
                    _('Estimated Cost'),
                    types['material'],
                    types['equipment'],
                    types['subcontract'],
                    _('Labor & Other'),
                    _('Actual Cost'),
                    _('Profit'),
                ],
                rows,
                [
                    Markup('<td>%s</td>') % _('Total'),
                    self._cell(data['contract_amount'], currency),
                    self._cell(data['revenue'], currency),
                    self._cell(data['estimated_cost'], currency),
                    self._cell(data['actual']['material'], currency),
                    self._cell(data['actual']['equipment'], currency),
                    self._cell(data['actual']['subcontract'], currency),
                    self._cell(data['actual']['labor'] + data['actual']['other'], currency),
                    self._cell(data['total_cost'], currency),
                    self._cell(data['profit'], currency),
                ],
            )
        )

        if data['equipment']:
            rows = []
            for values in data['equipment']:
                request = values['request']
                equipment = request.equipment_id or request.rented_equipment_id
                rows.append(
                    [
                        Markup('<td>%s</td>') % request.name,
                        Markup('<td>%s</td>')
                        % (equipment.display_name or request.description or ''),
                        Markup('<td>%s</td>')
                        % (request.boq_component_id.display_name or _('Outside BOQ')),
                        self._cell(values['planned'], currency),
                        self._cell(values['actual'], currency),
                        self._cell(values['committed'], currency),
                        self._cell(
                            values['planned'] - values['actual'] - values['committed'], currency
                        ),
                    ]
                )
            parts.append(Markup('<h4>%s</h4>') % _('Equipment Requests'))
            parts.append(
                self._html_table(
                    [
                        _('Request'),
                        _('Equipment'),
                        _('BOQ Equipment'),
                        _('Planned Cost'),
                        _('Actual Cost'),
                        _('Ordered, not Billed'),
                        _('Variance'),
                    ],
                    rows,
                    [
                        Markup('<td colspan="3">%s</td>') % _('Total'),
                        self._cell(sum(v['planned'] for v in data['equipment']), currency),
                        self._cell(sum(v['actual'] for v in data['equipment']), currency),
                        self._cell(sum(v['committed'] for v in data['equipment']), currency),
                        self._cell(
                            sum(
                                v['planned'] - v['actual'] - v['committed']
                                for v in data['equipment']
                            ),
                            currency,
                        ),
                    ],
                )
            )
        parts.append(
            Markup('<p class="text-muted small">%s</p>')
            % _(
                'Revenue and costs come from the posted journal items of the project cost center.'
                ' Stored materials are valued when delivered to the project warehouse (less'
                ' returns) and allocated to the BOQ items by their BOQ quantities.'
            )
        )
        parts.append(Markup('</div>'))
        return Markup('').join(parts)
