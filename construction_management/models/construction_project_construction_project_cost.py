"""Construction project construction project cost for construction management."""

from collections import defaultdict
from typing import Any, TypedDict

from odoo import api
from odoo import models

from .boq_consumption_common import (
    done_stock_moves,
    site_stock_move_domain,
    site_stock_move_sign,
    site_stock_move_value,
)
from .construction_boq import COST_TYPES
from .construction_project_cost import COST_REQUEST_STATES

from .runtime import model_attribute


class _CostReportTotals(TypedDict):
    """Amounts accumulated while building a project cost report."""

    estimated: dict[str, float]
    actual: dict[str, float]
    unallocated: dict[str, float]
    items: dict[int, dict]
    revenue: float
    unallocated_revenue: float


class ConstructionProject(models.Model):
    """Construction project."""

    _inherit = 'construction.project'

    def _get_cost_type_accounts(self):
        """{account id: cost type} used for the journal items without an explicit cost type."""
        self.ensure_one()
        company = self.company_id
        mapping = {}
        for field_name, cost_type in (
            ('construction_sub_expense_account_id', 'subcontract'),
            ('construction_labor_expense_account_id', 'labor'),
        ):
            if company[field_name]:
                mapping[company[field_name].id] = cost_type
        return mapping

    @api.model
    def _get_cost_type_of_line(self, line, account_types):
        if line.construction_cost_type:
            return line.construction_cost_type
        if line.account_id.id in account_types:
            return account_types[line.account_id.id]
        if line.move_id.construction_subcontract_invoice_id:
            return 'subcontract'
        if line.product_id and line.product_id.type == 'consu':
            return 'material'
        return 'other'

    def _get_material_site_costs(self, date_from=False, date_to=False):
        """Return costs of transfers and receipts by product, less warehouse and vendor returns.

        Consumption on site stays in the cost.
        """
        self.ensure_one()
        costs = defaultdict(float)
        warehouse = self.warehouse_id
        if not warehouse or not warehouse.view_location_id:
            return costs
        view = warehouse.view_location_id
        domain = [
            ('product_id.is_storable', '=', True),
            ('company_id', '=', self.company_id.id),
            *site_stock_move_domain(view, date_from, date_to),
        ]
        prefix = view.parent_path
        for move in done_stock_moves(self.env, domain):
            sign = site_stock_move_sign(move, prefix, ('internal', 'transit', 'supplier'))
            if sign:
                value = site_stock_move_value(move, self)
                costs[move.product_id] += sign * value
        return costs

    @staticmethod
    def _init_cost_report_totals(project) -> _CostReportTotals:
        """Set up the report totals and accumulate the BOQ estimates."""
        cost_types = [key for key, _label in COST_TYPES]
        estimated = dict.fromkeys(cost_types, 0.0)
        actual = dict.fromkeys(cost_types, 0.0)
        unallocated = dict.fromkeys(cost_types, 0.0)
        items = {}
        for item in project.boq_item_ids:
            items[item.id] = {
                'item': item,
                'contract': item.amount_total,
                'revenue': 0.0,
                'estimated': dict.fromkeys(cost_types, 0.0),
                'actual': dict.fromkeys(cost_types, 0.0),
            }
            for component in item.component_ids:
                items[item.id]['estimated'][component.component_type] += component.effective_cost
                estimated[component.component_type] += component.effective_cost
        return {
            'estimated': estimated,
            'actual': actual,
            'unallocated': unallocated,
            'items': items,
            'revenue': 0.0,
            'unallocated_revenue': 0.0,
        }

    @staticmethod
    def _cost_report_analytic_domain(
        analytic, date_from, date_to
    ) -> list[str | tuple[str, str, Any]]:
        """Select posted income and expense lines for the project cost center."""
        if not analytic:
            return []
        column = model_attribute(analytic.plan_id, '_column_name')()
        domain: list[str | tuple[str, str, Any]] = [
            (column, '=', analytic.id),
            ('move_line_id', '!=', False),
            ('move_line_id.parent_state', '=', 'posted'),
            ('general_account_id.internal_group', 'in', ('income', 'expense')),
        ]
        for operator, bound in (('>=', date_from), ('<=', date_to)):
            if bound:
                domain.append(('date', operator, bound))
        return domain

    def _add_cost_report_analytic_totals(
        self, project, totals: _CostReportTotals, date_from, date_to
    ):
        """Allocate analytic revenue and non-material costs to the BOQ and requests."""
        request_costs = defaultdict(float)
        domain = self._cost_report_analytic_domain(project.analytic_account_id, date_from, date_to)
        if not domain:
            return request_costs
        account_types = model_attribute(project, '_get_cost_type_accounts')()
        material_bill_lines = set(
            self.env['account.move.line']
            .sudo()
            .search(model_attribute(project, '_get_material_bill_domain')(date_from, date_to))
            .ids
        )
        items = totals['items']
        for analytic_line in self.env['account.analytic.line'].sudo().search(domain):
            line = analytic_line.move_line_id
            item_id = line.construction_boq_item_id.id
            if analytic_line.general_account_id.internal_group == 'income':
                totals['revenue'] += analytic_line.amount
                if item_id in items:
                    items[item_id]['revenue'] += analytic_line.amount
                else:
                    totals['unallocated_revenue'] += analytic_line.amount
                continue
            if line.product_id.is_storable or line.id in material_bill_lines:
                continue
            cost_type = model_attribute(project, '_get_cost_type_of_line')(line, account_types)
            amount = -analytic_line.amount
            totals['actual'][cost_type] += amount
            if item_id in items:
                items[item_id]['actual'][cost_type] += amount
            else:
                totals['unallocated'][cost_type] += amount
            if line.construction_equipment_request_id:
                request_costs[line.construction_equipment_request_id.id] += amount
        return request_costs

    def _add_cost_report_material_totals(
        self, project, totals: _CostReportTotals, date_from, date_to
    ):
        """Add material costs separately to avoid counting their analytic lines twice."""
        material_costs, material_unallocated = model_attribute(
            project, '_get_material_actual_costs'
        )(date_from, date_to)
        component_model = self.env['construction.boq.component'].sudo()
        items = totals['items']
        for component_id, cost in material_costs.items():
            totals['actual']['material'] += cost
            items[component_model.browse(component_id).item_id.id]['actual']['material'] += cost
        for cost in material_unallocated.values():
            totals['actual']['material'] += cost
            totals['unallocated']['material'] += cost

    def _get_cost_revenue_data(self, date_from=False, date_to=False):
        """Compare posted project revenue and costs to the BOQ estimate, by item and cost type."""
        self.ensure_one()
        project = self.sudo()
        totals = self._init_cost_report_totals(project)
        request_costs = self._add_cost_report_analytic_totals(project, totals, date_from, date_to)
        self._add_cost_report_material_totals(project, totals, date_from, date_to)

        requests = project.equipment_request_ids.filtered(lambda r: r.state in COST_REQUEST_STATES)
        committed = model_attribute(requests, '_get_committed_costs')()
        equipment = [
            {
                'request': request,
                'planned': request.requested_quantity * request.boq_component_id.unit_cost,
                'actual': request_costs.get(request.id, 0.0),
                'committed': committed.get(request.id, 0.0),
            }
            for request in requests
        ]

        for values in totals['items'].values():
            values['estimated_total'] = sum(values['estimated'].values())
            values['actual_total'] = sum(values['actual'].values())
        total_cost = sum(totals['actual'].values())
        revenue = totals['revenue']
        profit = revenue - total_cost
        return {
            'project': project,
            'currency': project.currency_id,
            'date_from': date_from,
            'date_to': date_to,
            'contract_amount': project.contract_amount,
            'estimated_cost': sum(totals['estimated'].values()),
            'progress': project.progress_percent,
            'revenue': revenue,
            'unallocated_revenue': totals['unallocated_revenue'],
            'estimated': totals['estimated'],
            'actual': totals['actual'],
            'unallocated': totals['unallocated'],
            'items': list(totals['items'].values()),
            'equipment': equipment,
            'total_cost': total_cost,
            'profit': profit,
            'margin': profit / revenue * 100.0 if revenue else 0.0,
        }

    def action_cost_revenue_report(self):
        """Cost revenue report."""
        self.ensure_one()
        report = self.env['construction.project.cost.report'].create({'project_id': self.id})
        return model_attribute(report, '_get_form_action')()
