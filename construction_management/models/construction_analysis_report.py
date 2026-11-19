"""Construction reports: one data builder per report, rendered on screen, in PDF and in Excel from
the same data."""

import base64
import io
import unicodedata
from collections import defaultdict

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero, format_date
from odoo.tools.misc import formatLang

from .construction_boq import COST_TYPES

from .runtime import model_attribute

REPORT_TYPES = [
    ('overview', 'Projects Overview'),
    ('boq', 'BOQ Progress & Cost'),
    ('owner_invoices', 'Owner Invoices Analysis'),
    ('subcontracts', 'Subcontractors Report'),
    ('materials', 'Material Consumption'),
    ('equipment', 'Equipment Operation & Cost'),
    ('guarantees', 'Guarantees & Retention'),
    ('budget', 'Budget vs Actual by Cost Type'),
]
REPORT_PROJECT_STATES = ('running', 'suspended', 'preliminary', 'final')
DATED_REPORTS = ('overview', 'owner_invoices', 'materials', 'equipment', 'budget')


class ConstructionAnalysisReport(models.TransientModel):
    """Construction analysis report."""

    _name = 'construction.analysis.report'
    _description = 'Construction Report'

    report_type = fields.Selection(REPORT_TYPES, string='Report', required=True, default='overview')
    project_ids = fields.Many2many(
        'construction.project',
        string='Projects',
        domain="[('state', 'not in', ('draft', 'cancelled'))]",
        help=(
            "Leave empty to report on all the started projects (in progress, suspended or handed"
            " over)."
        ),
    )
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    is_dated = fields.Boolean(compute='_compute_is_dated', string='Uses the Period')
    report_html = fields.Html(compute='_compute_report_html', sanitize=False, string='Report')

    @api.depends('report_type')
    def _compute_display_name(self):
        labels = dict(
            model_attribute(self._fields['report_type'], '_description_selection')(self.env)
        )
        for report in self:
            report.display_name = labels.get(report.report_type) or _('Construction Report')

    @api.depends('report_type')
    def _compute_is_dated(self):
        for report in self:
            report.is_dated = report.report_type in DATED_REPORTS

    @api.depends('report_type', 'project_ids', 'date_from', 'date_to')
    def _compute_report_html(self):
        for report in self:
            report.report_html = model_attribute(report, '_render_html')(
                model_attribute(report, '_get_report_data')()
            )

    def _check_period(self):
        for report in self:
            if report.date_from and report.date_to and report.date_from > report.date_to:
                raise UserError(_('The start of the period must be before its end.'))

    def action_print_pdf(self):
        """Print pdf."""
        self.ensure_one()
        self._check_period()
        return self.env.ref(
            'construction_management.action_report_construction_analysis'
        ).report_action(self)

    def action_export_xlsx(self):
        """Export xlsx."""
        self.ensure_one()
        self._check_period()
        data = self._get_report_data()
        content = self._render_xlsx(data)
        filename = f"{data['title']!s}.xlsx"
        attachment = self.env['ir.attachment'].create(
            {
                'name': filename,
                'datas': base64.b64encode(content),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            }
        )
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _get_projects(self):
        self.ensure_one()
        if self.project_ids:
            return self.project_ids.filtered(lambda p: p.state != 'cancelled')
        return self.env['construction.project'].search(
            [('state', 'in', REPORT_PROJECT_STATES)], order='name'
        )

    def _get_report_data(self):
        """{'title', 'period', 'currency', 'sections': [{'title', 'columns': [(label, type)],
        'rows': [{'values', 'css'}], 'total'}], 'notes'}: the report, independent of its output
        (screen, PDF, Excel).
        """
        self.ensure_one()
        labels = dict(
            model_attribute(self._fields['report_type'], '_description_selection')(self.env)
        )
        data = {
            'title': labels.get(self.report_type, ''),
            'period': (
                self._get_period_label() if self.report_type in DATED_REPORTS else _('Up to date')
            ),
            'currency': self.env.company.currency_id,
            'company': self.env.company,
            'sections': [],
            'notes': [],
        }
        projects = self._get_projects()
        if not projects:
            data['notes'].append(_('No project to report on.'))
            return data
        data['currency'] = projects[:1].currency_id
        builder = getattr(self, f'_report_{self.report_type}')
        builder(data, projects)
        return data

    def _get_period_label(self):
        if not self.date_from and not self.date_to:
            return _('All dates')
        start = format_date(self.env, self.date_from) if self.date_from else '...'
        end = format_date(self.env, self.date_to) if self.date_to else '...'
        return f'{start!s} - {end!s}'

    def _in_period(self, date):
        if not date:
            return not (self.date_from or self.date_to)
        return (not self.date_from or date >= self.date_from) and (
            not self.date_to or date <= self.date_to
        )

    @api.model
    def _selection_label(self, record, field_name):
        if not record[field_name]:
            return ''
        return dict(
            model_attribute(record._fields[field_name], '_description_selection')(record.env)
        ).get(record[field_name], '')

    @api.model
    def _row(self, values, css=''):
        return {'values': values, 'css': css}

    @api.model
    def _sum(self, rows, index):
        return sum(row['values'][index] or 0.0 for row in rows)

    @api.model
    def _percent(self, part, whole):
        return part / whole * 100.0 if whole else 0.0

    def _report_overview(self, data, projects):
        columns = [
            (_('Project'), 'text'),
            (_('Customer'), 'text'),
            (_('Status'), 'text'),
            (_('Contract Value'), 'monetary'),
            (_('Revenue (Invoiced)'), 'monetary'),
            (_('Actual Cost'), 'monetary'),
            (_('Gross Profit'), 'monetary'),
            (_('Margin (%)'), 'percent'),
            (_('Progress (%)'), 'percent'),
            (_('Certified (%)'), 'percent'),
            (_('Retention Balance'), 'monetary'),
            (_('Advance Remaining'), 'monetary'),
        ]
        rows = []
        for project in projects:
            figures = model_attribute(project, '_get_cost_revenue_data')(
                self.date_from, self.date_to
            )
            rows.append(
                self._row(
                    [
                        project.name,
                        project.partner_id.display_name,
                        self._selection_label(project, 'state'),
                        project.contract_amount,
                        figures['revenue'],
                        figures['total_cost'],
                        figures['profit'],
                        figures['margin'],
                        project.progress_percent,
                        project.certified_progress_percent,
                        project.retention_balance,
                        project.advance_balance,
                    ]
                )
            )
        revenue, cost = self._sum(rows, 4), self._sum(rows, 5)
        total = [
            _('Total'),
            '',
            '',
            self._sum(rows, 3),
            revenue,
            cost,
            revenue - cost,
            self._percent(revenue - cost, revenue),
            None,
            None,
            self._sum(rows, 10),
            self._sum(rows, 11),
        ]
        data['sections'].append({'title': '', 'columns': columns, 'rows': rows, 'total': total})
        data['notes'].append(
            _(
                'Revenue: posted customer invoices of the period. Actual cost: posted costs of the '
                'period (materials, equipment, subcontractors, labor and other costs).'
            )
        )

    def _report_boq(self, data, projects):
        columns = [
            (_('Code'), 'text'),
            (_('Item'), 'text'),
            (_('Unit'), 'text'),
            (_('Quantity'), 'float'),
            (_('Weight (%)'), 'percent'),
            (_('Progress (%)'), 'percent'),
            (_('Certified Quantity'), 'float'),
            (_('Certified (%)'), 'percent'),
            (_('Estimated Cost'), 'monetary'),
            (_('Actual Cost'), 'monetary'),
            (_('Variance'), 'monetary'),
            (_('Cost Consumed (%)'), 'percent'),
        ]
        for project in projects:
            rows = []
            for item in project.boq_item_ids:
                rows.append(
                    self._row(
                        [
                            item.code or '',
                            item.name,
                            item.uom_id.name or '',
                            item.total_quantity,
                            item.weight_percent,
                            item.progress_percent,
                            item.certified_quantity,
                            item.executed_percent,
                            item.estimated_cost,
                            item.actual_cost,
                            item.estimated_cost - item.actual_cost,
                            item.cost_consumed_percent,
                        ]
                    )
                )
            estimated, actual = self._sum(rows, 8), self._sum(rows, 9)
            total = [
                _('Total'),
                '',
                '',
                None,
                self._sum(rows, 4),
                project.progress_percent,
                None,
                project.certified_progress_percent,
                estimated,
                actual,
                estimated - actual,
                self._percent(actual, estimated),
            ]
            data['sections'].append(
                {'title': project.name, 'columns': columns, 'rows': rows, 'total': total}
            )
        data['notes'].append(
            _(
                'Progress: consumption of the materials, equipment and subcontracted works of the '
                'item. Certified: quantities of the approved owner invoices. Project totals are '
                'weighted by the item weights (estimated cost share).'
            )
        )

    def _report_owner_invoices(self, data, projects):
        columns = [
            (_('Invoice'), 'text'),
            (_('Date'), 'date'),
            (_('Type'), 'text'),
            (_('Status'), 'text'),
            (_('Works / Advance'), 'monetary'),
            (_('Work Guarantee'), 'monetary'),
            (_('Advance Deduction'), 'monetary'),
            (_('Final Insurance'), 'monetary'),
            (_('Other Deductions'), 'monetary'),
            (_('Net Amount'), 'monetary'),
            (_('Payment Status'), 'text'),
        ]
        grand = [0.0] * 6
        for project in projects:
            invoices = project.owner_invoice_ids.filtered(
                lambda inv: inv.state in ('approved', 'invoiced') and self._in_period(inv.date)
            ).sorted(lambda inv: (inv.date, inv.id))
            if not invoices:
                continue
            rows = []
            for invoice in invoices:
                works = (
                    invoice.advance_amount
                    if invoice.invoice_type == 'advance'
                    else invoice.gross_amount
                )
                payment = invoice.sudo().move_id
                rows.append(
                    self._row(
                        [
                            invoice.name,
                            invoice.date,
                            self._selection_label(invoice, 'invoice_type'),
                            self._selection_label(invoice, 'state'),
                            works,
                            invoice.retention_amount,
                            invoice.advance_deduction_amount,
                            invoice.insurance_amount,
                            invoice.deduction_total,
                            invoice.net_amount,
                            self._selection_label(payment, 'payment_state') if payment else '',
                        ]
                    )
                )
            sums = [self._sum(rows, index) for index in range(4, 10)]
            grand = [a + b for a, b in zip(grand, sums)]
            data['sections'].append(
                {
                    'title': project.name,
                    'columns': columns,
                    'rows': rows,
                    'total': [_('Total'), None, '', ''] + sums + [''],
                }
            )
        if len(data['sections']) > 1:
            data['sections'].append(
                {
                    'title': _('All Projects'),
                    'columns': columns,
                    'rows': [],
                    'total': [_('Grand Total'), None, '', ''] + grand + [''],
                }
            )
        if not data['sections']:
            data['notes'].append(_('No approved owner invoice in the period.'))

    def _report_subcontracts(self, data, projects):
        columns = [
            (_('Contract'), 'text'),
            (_('Subcontractor'), 'text'),
            (_('Status'), 'text'),
            (_('Contract Value'), 'monetary'),
            (_('Invoiced'), 'monetary'),
            (_('Executed (%)'), 'percent'),
            (_('Remaining'), 'monetary'),
            (_('Guarantee Held'), 'monetary'),
            (_('Guarantee Refunded'), 'monetary'),
            (_('Guarantee Balance'), 'monetary'),
            (_('Advance Payment'), 'monetary'),
            (_('Advance Remaining'), 'monetary'),
        ]
        for project in projects:
            contracts = project.subcontract_ids.filtered(
                lambda c: c.state in ('active', 'closed', 'to_approve')
            )
            if not contracts:
                continue
            rows = []
            for contract in contracts.sorted(lambda c: (c.partner_id.name or '', c.id)):
                rows.append(
                    self._row(
                        [
                            contract.name,
                            contract.partner_id.display_name,
                            self._selection_label(contract, 'state'),
                            contract.amount_total,
                            contract.invoiced_amount,
                            self._percent(contract.invoiced_amount, contract.amount_total),
                            contract.amount_total - contract.invoiced_amount,
                            contract.guarantee_held,
                            contract.guarantee_refunded,
                            contract.guarantee_balance,
                            contract.advance_amount,
                            contract.advance_balance,
                        ]
                    )
                )
            value, invoiced = self._sum(rows, 3), self._sum(rows, 4)
            total = [
                _('Total'),
                '',
                '',
                value,
                invoiced,
                self._percent(invoiced, value),
                value - invoiced,
            ] + [self._sum(rows, index) for index in range(7, 12)]
            data['sections'].append(
                {'title': project.name, 'columns': columns, 'rows': rows, 'total': total}
            )
        if not data['sections']:
            data['notes'].append(_('No subcontract on the selected projects.'))

    def _report_materials(self, data, projects):
        columns = [
            (_('Material'), 'text'),
            (_('Unit'), 'text'),
            (_('BOQ Quantity'), 'float'),
            (_('Requested'), 'float'),
            (_('Purchased'), 'float'),
            (_('Received'), 'float'),
            (_('Billed'), 'float'),
            (_('Remaining BOQ Quantity'), 'float'),
            (_('Received (%)'), 'percent'),
            (_('Actual Cost'), 'monetary'),
        ]
        line_model = self.env['construction.material.request.line']
        for project in projects:
            lines = line_model.search(
                [
                    ('project_id', '=', project.id),
                    ('request_id.state', 'in', ('to_approve', 'approved', 'done')),
                ]
            )
            lines = lines.filtered(lambda l: self._in_period(l.request_id.date))
            by_requirement = defaultdict(lambda: line_model.browse())
            for line in lines:
                by_requirement[line.requirement_id] |= line
            requirements = project.material_requirement_ids | lines.requirement_id
            rows = []
            for requirement in requirements.sorted(lambda r: r.product_id.display_name or ''):
                requirement_lines = by_requirement[requirement]
                received = sum(requirement_lines.mapped('received_quantity'))
                if not requirement_lines and not requirement.boq_quantity:
                    continue
                rows.append(
                    self._row(
                        [
                            requirement.product_id.display_name,
                            requirement.uom_id.name or '',
                            requirement.boq_quantity,
                            sum(requirement_lines.mapped('quantity')),
                            sum(requirement_lines.mapped('purchased_quantity')),
                            received,
                            sum(requirement_lines.mapped('billed_quantity')),
                            requirement.boq_quantity - received,
                            self._percent(received, requirement.boq_quantity),
                            sum(requirement_lines.mapped('actual_cost')),
                        ]
                    )
                )
            if not rows:
                continue
            total = [_('Total'), '', None, None, None, None, None, None, None, self._sum(rows, 9)]
            data['sections'].append(
                {'title': project.name, 'columns': columns, 'rows': rows, 'total': total}
            )
        if not data['sections']:
            data['notes'].append(_('No material on the selected projects.'))
        data['notes'].append(
            _(
                'Received: quantities actually received in the project warehouse, net of the '
                'returns. Actual cost: posted vendor bills (purchases) or value of the transfers '
                'from the other warehouses.'
            )
        )

    def _report_equipment(self, data, projects):
        columns = [
            (_('Request'), 'text'),
            (_('Equipment'), 'text'),
            (_('Source'), 'text'),
            (_('BOQ Item'), 'text'),
            (_('Unit'), 'text'),
            (_('Requested'), 'float'),
            (_('Consumed'), 'float'),
            (_('Consumed (%)'), 'percent'),
            (_('Planned Cost'), 'monetary'),
            (_('Actual Cost'), 'monetary'),
            (_('Ordered, not Billed'), 'monetary'),
            (_('Variance vs Plan'), 'monetary'),
        ]
        for project in projects:
            requests = project.equipment_request_ids.filtered(
                lambda r: r.state in ('assigned', 'rental', 'done') and self._request_in_period(r)
            )
            if not requests:
                continue
            rows = []
            for request in requests.sorted(lambda r: (r.date_from, r.id)):
                rented = request.state == 'rental' or (request.equipment_id.ownership == 'rented')
                equipment = request.equipment_id or request.rented_equipment_id
                rows.append(
                    self._row(
                        [
                            request.name,
                            equipment.display_name or request.description,
                            _('Rented') if rented else _('Company Owned'),
                            request.boq_item_id.display_name or '',
                            request.boq_uom_id.name or '',
                            request.requested_quantity,
                            request.consumed_quantity,
                            self._percent(request.consumed_quantity, request.requested_quantity),
                            request.planned_cost,
                            request.actual_cost,
                            request.committed_cost,
                            request.cost_variance,
                        ]
                    )
                )
            total = [_('Total'), '', '', '', '', None, None, None] + [
                self._sum(rows, index) for index in range(8, 12)
            ]
            data['sections'].append(
                {'title': project.name, 'columns': columns, 'rows': rows, 'total': total}
            )
        if not data['sections']:
            data['notes'].append(_('No equipment request on the selected projects in the period.'))
        data['notes'].append(
            _(
                'Consumed: posted operating hours of the company equipment and hours billed by the '
                'rental vendors. Actual cost includes the rented hours worked and not billed yet.'
            )
        )

    def _request_in_period(self, request):
        """Equipment requests whose period overlaps the report period."""
        if self.date_to and request.date_from and request.date_from > self.date_to:
            return False
        if self.date_from and request.date_to and request.date_to < self.date_from:
            return False
        return True

    def _report_guarantees(self, data, projects):
        letter_columns = [
            (_('Reference'), 'text'),
            (_('Guarantee Number'), 'text'),
            (_('Type'), 'text'),
            (_('Direction'), 'text'),
            (_('Party'), 'text'),
            (_('Bank'), 'text'),
            (_('Amount'), 'monetary'),
            (_('Issue Date'), 'date'),
            (_('Expiry Date'), 'date'),
            (_('Days to Expiry'), 'int'),
            (_('Status'), 'text'),
        ]
        balance_columns = [
            (_('Description'), 'text'),
            (_('Party'), 'text'),
            (_('Held / Paid'), 'monetary'),
            (_('Refunded'), 'monetary'),
            (_('Balance'), 'monetary'),
        ]
        for project in projects:
            guarantees = project.guarantee_ids.filtered(
                lambda g: g.state in ('active', 'expired', 'released')
            )
            rows = []
            for guarantee in guarantees.sorted(
                lambda g: (g.expiry_date or fields.Date.today(), g.id)
            ):
                party = (
                    guarantee.beneficiary_id
                    if guarantee.direction == 'issued'
                    else guarantee.applicant_id
                )
                expiring = (
                    guarantee.state == 'active'
                    and guarantee.expiry_date
                    and guarantee.days_to_expiry <= 30
                )
                rows.append(
                    self._row(
                        [
                            guarantee.name,
                            guarantee.reference or '',
                            self._selection_label(guarantee, 'guarantee_type'),
                            self._selection_label(guarantee, 'direction'),
                            party.display_name or '',
                            guarantee.bank_id.name or '',
                            guarantee.amount,
                            guarantee.issue_date,
                            guarantee.expiry_date,
                            guarantee.days_to_expiry if guarantee.state == 'active' else None,
                            self._selection_label(guarantee, 'state'),
                        ],
                        css='text-danger' if expiring else '',
                    )
                )
            if rows:
                data['sections'].append(
                    {
                        'title': f"{project.name!s} - {_('Bank & Cash Guarantees')!s}",
                        'columns': letter_columns,
                        'rows': rows,
                        'total': [
                            _('Total'),
                            '',
                            '',
                            '',
                            '',
                            '',
                            sum(row['values'][6] for row in rows),
                            None,
                            None,
                            None,
                            '',
                        ],
                    }
                )
            balances = [
                self._row(
                    [
                        _('Work Guarantee (Retention) - Owner'),
                        project.partner_id.display_name,
                        project.retention_held,
                        project.retention_refunded,
                        project.retention_balance,
                    ]
                ),
                self._row(
                    [
                        _('Final Insurance - Owner'),
                        project.partner_id.display_name,
                        project.insurance_paid,
                        project.insurance_refunded,
                        project.insurance_paid - project.insurance_refunded,
                    ]
                ),
            ]
            for contract in project.subcontract_ids.filtered(
                lambda c: c.state in ('active', 'closed')
            ):
                if float_is_zero(
                    contract.guarantee_held, precision_rounding=contract.currency_id.rounding
                ):
                    continue
                balances.append(
                    self._row(
                        [
                            f"{_('Subcontractor Work Guarantee')!s} - {contract.name!s}",
                            contract.partner_id.display_name,
                            contract.guarantee_held,
                            contract.guarantee_refunded,
                            contract.guarantee_balance,
                        ]
                    )
                )
            data['sections'].append(
                {
                    'title': f"{project.name!s} - {_('Retention & Insurance Balances')!s}",
                    'columns': balance_columns,
                    'rows': balances,
                    'total': None,
                }
            )
        data['notes'].append(_('Guarantees in red expire within 30 days.'))

    def _report_budget(self, data, projects):
        columns = [
            (_('Cost Type'), 'text'),
            (_('Estimated Cost'), 'monetary'),
            (_('Actual Cost'), 'monetary'),
            (_('Variance'), 'monetary'),
            (_('Variance (%)'), 'percent'),
            (_('Consumed (%)'), 'percent'),
        ]
        type_labels = dict(COST_TYPES)
        type_labels.update(
            model_attribute(
                self.env['construction.boq.component']._fields['component_type'],
                '_description_selection',
            )(self.env)
        )
        type_labels['other'] = _('Other Costs')
        for project in projects:
            figures = model_attribute(project, '_get_cost_revenue_data')(
                self.date_from, self.date_to
            )
            rows = []
            for cost_type, _label in COST_TYPES:
                estimated = figures['estimated'].get(cost_type, 0.0)
                actual = figures['actual'].get(cost_type, 0.0)
                if float_is_zero(estimated, precision_digits=2) and float_is_zero(
                    actual, precision_digits=2
                ):
                    continue
                variance = estimated - actual
                rows.append(
                    self._row(
                        [
                            type_labels.get(cost_type, cost_type),
                            estimated,
                            actual,
                            variance,
                            self._percent(variance, estimated),
                            self._percent(actual, estimated),
                        ],
                        css='' if variance >= 0 else 'text-danger',
                    )
                )
            estimated = figures['estimated_cost']
            actual = figures['total_cost']
            total = [
                _('Total'),
                estimated,
                actual,
                estimated - actual,
                self._percent(estimated - actual, estimated),
                self._percent(actual, estimated),
            ]
            summary = [
                self._row(
                    [_('Contract Value'), figures['contract_amount'], None, None, None, None],
                    css='fw-bold',
                ),
                self._row(
                    [_('Revenue (Invoiced)'), None, figures['revenue'], None, None, None],
                    css='fw-bold',
                ),
                self._row(
                    [_('Gross Profit'), None, figures['profit'], None, figures['margin'], None],
                    css='fw-bold',
                ),
            ]
            data['sections'].append(
                {
                    'title': project.name,
                    'columns': columns,
                    'rows': rows,
                    'total': total,
                    'footer_rows': summary,
                }
            )
        data['notes'].append(
            _(
                'Variance = estimated - actual: a negative variance (in red) is an overrun of the '
                'BOQ estimate.'
            )
        )

    def _format_value(self, value, value_type, currency):
        if value is None or value == '':
            return ''
        if value_type == 'text':
            return str(value)
        if value_type == 'date':
            return format_date(self.env, value) if value else ''
        if value_type == 'monetary':
            return formatLang(self.env, value, digits=currency.decimal_places)
        if value_type == 'percent':
            return f'{formatLang(self.env, value, digits=1)!s} %'
        if value_type == 'int':
            return str(int(value))
        return formatLang(self.env, value, digits=2)

    def _is_rtl(self):
        return (
            model_attribute(self.env['res.lang'], '_get_data')(
                code=self.env.lang or 'en_US'
            ).direction
            == 'rtl'
        )

    def _get_pdf_html(self):
        """HTML of the PDF: same content as the screen, with the text cells laid out for
        wkhtmltopdf."""
        self.ensure_one()
        return self._render_html(self._get_report_data(), pdf=True)

    @api.model
    def _text(self, value, pdf=False, rtl=False):
        """Text of a cell. wkhtmltopdf (PDF engine) misplaces right-to-left texts mixing Arabic with
        Latin letters or digits (codes, sizes, references): such texts are rendered in an
        explicit right-to-left block, which it lays out correctly. Pure Arabic or pure Latin
        texts are left as they are.
        """
        value = str(value or '')
        if not (pdf and rtl) or not value:
            return value

        value = ''.join(char for char in value if unicodedata.category(char) != 'Mn')
        directions = {unicodedata.bidirectional(char) for char in value}
        if directions & {'AL', 'R'} and directions & {'L', 'EN', 'AN'}:
            return (
                Markup('<span style="direction: rtl; unicode-bidi: bidi-override;">%s</span>')
                % value
            )
        return value

    def _render_html(self, data, pdf=False):
        currency = data['currency']
        rtl = self._is_rtl()
        parts = [Markup('<div class="o_construction_analysis">')]
        info = [
            (_('Company'), data['company'].name),
            (_('Period'), data['period']),
            (_('Currency'), currency.name or ''),
            (_('Printed on'), format_date(self.env, fields.Date.context_today(self))),
        ]
        parts.append(Markup('<h3>%s</h3>') % data['title'])

        parts.append(
            Markup(
                '<table class="table table-sm table-bordered mb-2 o_construction_analysis_info">'
                '<thead class="table-light"><tr>%s</tr></thead><tbody><tr>%s</tr></tbody></table>'
            )
            % (
                Markup('').join(Markup('<th>%s</th>') % label for label, _value in info),
                Markup('').join(
                    Markup('<td class="fw-bold">%s</td>') % self._text(value, pdf, rtl)
                    for _label, value in info
                ),
            )
        )
        for section in data['sections']:
            columns = section['columns']
            if section.get('title'):
                parts.append(
                    Markup('<h5 class="mt-3">%s</h5>') % self._text(section['title'], pdf, rtl)
                )
            head = Markup('').join(
                Markup('<th class="%s">%s</th>') % ('' if col_type == 'text' else 'text-end', label)
                for label, col_type in columns
            )
            body = []
            all_rows = list(section['rows'])
            footer_rows = section.get('footer_rows') or []
            for row in all_rows:
                body.append(self._html_row(row['values'], columns, currency, row['css'], pdf, rtl))
            foot = []
            if section.get('total'):
                foot.append(
                    self._html_row(section['total'], columns, currency, 'fw-bold', pdf, rtl)
                )
            for row in footer_rows:
                foot.append(self._html_row(row['values'], columns, currency, row['css'], pdf, rtl))
            parts.append(
                Markup(
                    '<table class="table table-sm table-striped table-bordered'
                    ' o_construction_analysis_table">'
                    '<thead'
                    ' class="table-light"><tr>%s</tr></thead>'
                    '<tbody>%s</tbody><tfoot>%s</tfoot></table>'
                )
                % (head, Markup('').join(body), Markup('').join(foot))
            )
        if data['notes'] and not (pdf and rtl):

            parts.append(
                Markup(
                    '<table class="table table-sm table-bordered mt-2 small text-muted '
                    'o_construction_analysis_notes">%s</table>'
                )
                % Markup('').join(Markup('<tr><td>%s</td></tr>') % note for note in data['notes'])
            )
        parts.append(Markup('</div>'))
        return Markup('').join(parts)

    def _html_row(self, values, columns, currency, css, pdf=False, rtl=False):
        cells = []
        for value, (_label, col_type) in zip(values, columns):
            classes = '' if col_type == 'text' else 'text-end text-nowrap'
            if (
                col_type in ('monetary', 'float', 'percent')
                and isinstance(value, (int, float))
                and value < 0
                and not float_is_zero(value, precision_digits=2)
            ):
                classes += ' text-danger'
            text = self._format_value(value, 'text' if col_type == 'text' else col_type, currency)
            cells.append(
                Markup('<td class="%s">%s</td>')
                % (classes, self._text(text, pdf, rtl) if col_type == 'text' else text)
            )
        return Markup('<tr class="%s">%s</tr>') % (css or '', Markup('').join(cells))

    def _render_xlsx(self, data):
        import xlsxwriter

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(data['title'][:31])
        if self._is_rtl():
            sheet.right_to_left()
        currency = data['currency']
        money = f"#,##0.{'0' * currency.decimal_places}" if currency.decimal_places else '#,##0'
        styles = {
            'title': workbook.add_format({'bold': True, 'font_size': 14}),
            'muted': workbook.add_format({'italic': True, 'font_color': '#666666'}),
            'section': workbook.add_format({'bold': True, 'font_size': 12, 'bg_color': '#E9ECEF'}),
            'header': workbook.add_format(
                {
                    'bold': True,
                    'bg_color': '#714B67',
                    'font_color': '#FFFFFF',
                    'border': 1,
                    'text_wrap': True,
                    'valign': 'vcenter',
                }
            ),
        }
        number_formats = {
            'monetary': money,
            'float': '#,##0.00',
            'percent': '0.0"%"',
            'int': '0',
            'date': 'yyyy-mm-dd',
            'text': '@',
        }
        cell_formats = {}

        def cell_format(col_type, bold=False, red=False):
            """Cell format."""
            key = (col_type, bold, red)
            if key not in cell_formats:
                options = {'border': 1, 'num_format': number_formats.get(col_type, '@')}
                if bold:
                    options['bold'] = True
                    options['bg_color'] = '#F8F9FA'
                if red:
                    options['font_color'] = '#DC3545'
                cell_formats[key] = workbook.add_format(options)
            return cell_formats[key]

        sheet.write(0, 0, data['title'], styles['title'])
        sheet.write(
            1,
            0,
            f"{_('Company')!s}: {data['company'].name!s}  |  "
            f"{_('Period')!s}: {data['period']!s}  |  "
            f"{_('Currency')!s}: {currency.name or ''!s}  |  "
            f"{_('Printed on')!s}: {format_date(self.env, fields.Date.context_today(self))!s}",
            styles['muted'],
        )
        row_index = 3
        widths = defaultdict(lambda: 10)
        for section in data['sections']:
            columns = section['columns']
            if section.get('title'):
                sheet.merge_range(
                    row_index, 0, row_index, len(columns) - 1, section['title'], styles['section']
                )
                row_index += 1
            for col, (label, _col_type) in enumerate(columns):
                sheet.write(row_index, col, label, styles['header'])
                widths[col] = max(widths[col], min(len(label) + 2, 30))
            row_index += 1
            rows = [(row['values'], row['css']) for row in section['rows']]
            if section.get('total'):
                rows.append((section['total'], 'fw-bold'))
            rows += [
                (row['values'], row['css'] or 'fw-bold') for row in section.get('footer_rows') or []
            ]
            for values, css in rows:
                bold = 'fw-bold' in (css or '')
                red_row = 'text-danger' in (css or '')
                for col, (value, (_label, col_type)) in enumerate(zip(values, columns)):
                    if value is None or value == '':
                        sheet.write_blank(row_index, col, None, cell_format('text', bold))
                        continue
                    red = red_row or (
                        col_type in ('monetary', 'float', 'percent')
                        and isinstance(value, (int, float))
                        and value < -0.005
                    )
                    if col_type == 'date':
                        sheet.write_datetime(
                            row_index,
                            col,
                            fields.Datetime.to_datetime(value),
                            cell_format(col_type, bold, red),
                        )
                    elif col_type == 'text':
                        sheet.write_string(
                            row_index, col, str(value), cell_format(col_type, bold, red)
                        )
                        widths[col] = max(widths[col], min(len(str(value)) + 2, 45))
                    else:
                        sheet.write_number(row_index, col, value, cell_format(col_type, bold, red))
                        widths[col] = max(widths[col], 14)
                row_index += 1
            row_index += 1
        for note in data['notes']:
            sheet.write(row_index, 0, note, styles['muted'])
            row_index += 1
        for col, width in widths.items():
            sheet.set_column(col, col, width)
        workbook.close()
        return output.getvalue()
