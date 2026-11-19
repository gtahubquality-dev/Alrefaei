"""Construction boq component for construction management."""

from collections import defaultdict
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.tools import float_round
from .construction_boq_consumption import SUBCONTRACT_EXECUTED_STATES, REQUEST_LINE_STATES

from .runtime import model_attribute


class ConstructionBoqComponent(models.Model):
    """Construction boq component."""

    _inherit = 'construction.boq.component'

    requested_quantity = fields.Float(
        help=(
            "Materials: quantity requested on material requests. Equipment: quantity of the"
            " equipment requests. Subcontracted works: quantity assigned on subcontracts."
        )
    )
    consumed_quantity = fields.Float(
        help=(
            "Materials: quantity delivered to the project warehouse (net of returns). Equipment:"
            " operating hours and hours billed by the rental vendors. Subcontracted works: quantity"
            " executed on the subcontractor invoices approved by the site."
        )
    )
    requested_percent = fields.Float(
        compute='_compute_consumption',
        string='Requested (%)',
        help=(
            "Requested (materials, equipment) or assigned (subcontracts) quantity over the BOQ"
            " quantity."
        ),
    )
    request_line_ids = fields.One2many(
        'construction.material.request.line', 'boq_component_id', string='Material Request Lines'
    )
    subcontract_line_ids = fields.One2many(
        'construction.subcontract.line', 'boq_component_id', string='Subcontract Lines'
    )

    def _compute_consumption(self):
        """Requested and consumed quantities of materials and subcontracted works, in the unit of
        the component (equipment: see the parent method). Quantities of documents linked to no
        specific BOQ item (material used by several items, item with several subcontracted works)
        are spread over the components in proportion to their BOQ quantities.
        """
        super()._compute_consumption()
        materials = self.filtered(
            lambda c: c.component_type == 'material' and c.id and c.product_id
        )
        subcontracts = self.filtered(lambda c: c.component_type == 'subcontract' and c.id)
        values = {}
        if materials:
            values.update(model_attribute(materials, '_get_material_consumption')())
        if subcontracts:
            values.update(model_attribute(subcontracts, '_get_subcontract_consumption')())
        for component in materials | subcontracts:
            requested, consumed = values.get(component.id, (0.0, 0.0))
            component.requested_quantity = requested
            component.consumed_quantity = consumed
        for component in self:

            precision = self.env['decimal.precision'].precision_get('Product Unit')
            component.requested_quantity = float_round(
                component.requested_quantity, precision_digits=precision
            )
            component.consumed_quantity = float_round(
                component.consumed_quantity, precision_digits=precision
            )
            component.remaining_consumption = float_round(
                component.effective_quantity - component.consumed_quantity,
                precision_digits=precision,
            )
            component.consumption_percent = (
                component.consumed_quantity / component.effective_quantity * 100.0
                if component.effective_quantity
                else 0.0
            )
            component.requested_percent = (
                component.requested_quantity / component.effective_quantity * 100.0
                if component.effective_quantity
                else 0.0
            )

    @api.model
    def _spread(self, totals, linked, components_of, weight):
        """{component id: quantity}: quantities linked to each component, plus the unlinked rest of
        each group spread over its components in proportion to the weights.
        """
        result = defaultdict(float)
        for key, components in components_of.items():
            rest = totals.get(key, 0.0) - sum(linked.get(c.id, 0.0) for c in components)
            total_weight = sum(weight(c) for c in components)
            for component in components:
                result[component.id] += linked.get(component.id, 0.0)
                if total_weight:
                    result[component.id] += rest * weight(component) / total_weight
                elif len(components) == 1:
                    result[component.id] += rest
        return result

    def _material_components_of(self, project):
        """{product id: material components of the project using it} for the products of self."""
        components = self.sudo().search(
            [
                ('project_id', '=', project.id),
                ('component_type', '=', 'material'),
                ('product_id', 'in', self.product_id.ids),
            ]
        )
        components_of = defaultdict(lambda: self.browse())
        for component in components:
            components_of[component.product_id.id] |= component
        return components_of

    def _get_material_consumption(self):
        """{component id: (requested, delivered)} of material components, in the component unit."""
        requirement_model = self.env['construction.material.requirement']
        result = {}
        for project in self.project_id:
            project_components = self.filtered(lambda c, p=project: c.project_id == p)
            components_of = model_attribute(project_components, '_material_components_of')(project)
            product_ids = list(components_of)

            def weight(component):
                """Weight."""
                return model_attribute(requirement_model, '_convert')(
                    component.effective_quantity, component.uom_id, component.product_id
                )

            requested_total, requested_linked = defaultdict(float), defaultdict(float)
            for line in (
                self.env['construction.material.request.line']
                .sudo()
                .search(
                    [
                        ('request_id.project_id', '=', project.id),
                        ('request_id.state', 'in', REQUEST_LINE_STATES),
                        ('product_id', 'in', product_ids),
                    ]
                )
            ):
                quantity = model_attribute(requirement_model, '_convert')(
                    line.quantity, line.uom_id, line.product_id
                )
                requested_total[line.product_id.id] += quantity
                if line.boq_component_id:
                    requested_linked[line.boq_component_id.id] += quantity

            delivered_total, delivered_linked = defaultdict(float), defaultdict(float)
            for move, sign in model_attribute(project, '_get_material_site_moves')(product_ids):
                quantity = sign * model_attribute(requirement_model, '_convert')(
                    move.quantity, move.product_uom, move.product_id
                )
                delivered_total[move.product_id.id] += quantity
                origin = move.origin_returned_move_id or move
                source_line = (
                    origin.construction_material_line_id
                    or origin.purchase_line_id.construction_material_line_id
                )
                if source_line.boq_component_id:
                    delivered_linked[source_line.boq_component_id.id] += quantity

            requested = self._spread(requested_total, requested_linked, components_of, weight)
            delivered = self._spread(delivered_total, delivered_linked, components_of, weight)
            for component in project_components:
                base_uom = component.product_id.uom_id
                uom = component.uom_id or base_uom
                result[component.id] = tuple(
                    model_attribute(base_uom, '_compute_quantity')(
                        data[component.id], uom, round=False, raise_if_failure=False
                    )
                    for data in (requested, delivered)
                )
        return result

    def _get_subcontract_consumption(self):
        """{component id: (assigned on subcontracts, executed)} of subcontracted works, in the item
        unit."""
        items = self.item_id
        components_of = {
            item.id: item.component_ids.filtered(lambda c: c.component_type == 'subcontract')
            for item in items
        }
        assigned_total, assigned_linked = defaultdict(float), defaultdict(float)
        executed_total, executed_linked = defaultdict(float), defaultdict(float)
        lines = (
            self.env['construction.subcontract.line']
            .sudo()
            .search(
                [
                    ('boq_item_id', 'in', items.ids),
                    ('contract_id.state', 'in', ('active', 'closed')),
                ]
            )
        )
        for line in lines:
            executed = line.executed_quantity
            assigned_total[line.boq_item_id.id] += line.quantity
            executed_total[line.boq_item_id.id] += executed
            if line.boq_component_id:
                assigned_linked[line.boq_component_id.id] += line.quantity
                executed_linked[line.boq_component_id.id] += executed

        def weight(component):
            """Weight."""
            return component.effective_quantity

        assigned = self._spread(assigned_total, assigned_linked, components_of, weight)
        executed = self._spread(executed_total, executed_linked, components_of, weight)
        result = {}
        for component in self:

            total = component.item_id.total_quantity
            ratio = component.effective_quantity / total if total else 1.0
            result[component.id] = (assigned[component.id] * ratio, executed[component.id] * ratio)
        return result

    def _get_subcontract_executed_costs(self):
        """{component id: cost of the quantities executed on the subcontractor invoices approved by
        the site (and later stages), at the subcontract unit prices}. Lines covering no specific
        subcontracted work are shared over the works of the item in proportion to their BOQ cost.
        """
        items = self.item_id
        components_of = {
            item.id: item.component_ids.filtered(lambda c: c.component_type == 'subcontract')
            for item in items
        }
        total, linked = defaultdict(float), defaultdict(float)
        invoice_lines = (
            self.env['construction.subcontract.invoice.line']
            .sudo()
            .search(
                [
                    ('contract_line_id.boq_item_id', 'in', items.ids),
                    ('invoice_id.state', 'in', SUBCONTRACT_EXECUTED_STATES),
                ]
            )
        )
        for invoice_line in invoice_lines:
            contract_line = invoice_line.contract_line_id
            contract = contract_line.contract_id
            amount = model_attribute(contract.currency_id, '_convert')(
                invoice_line.current_quantity * invoice_line.unit_price,
                contract.company_id.currency_id,
                contract.company_id,
                invoice_line.invoice_id.date or fields.Date.today(),
            )
            total[contract_line.boq_item_id.id] += amount
            if contract_line.boq_component_id:
                linked[contract_line.boq_component_id.id] += amount
        costs = self._spread(total, linked, components_of, lambda c: c.effective_cost)
        return {component.id: costs[component.id] for component in self}

    def _compute_actual_cost(self):
        """Subcontracted works: cost of the executed quantities approved (subcontractor invoices
        approved by the site), so that 50 executed of 100 cost 50 x the subcontract price.

        Materials: cost of the posted vendor bills of the purchases of the project (and value of the
        transfers from the other warehouses), charged to the BOQ item they were requested for, the
        rest shared over the BOQ items by delivered quantities.
        """
        super()._compute_actual_cost()
        subcontracts = self.filtered(lambda c: c.component_type == 'subcontract' and c.id)
        if subcontracts:
            executed = model_attribute(subcontracts, '_get_subcontract_executed_costs')()
            for component in subcontracts:
                component.actual_cost = executed.get(component.id, 0.0)
                component.cost_variance = component.effective_cost - component.actual_cost
        materials = self.filtered(
            lambda c: c.component_type == 'material' and c.id and c.product_id
        )
        if not materials:
            return
        manual = dict(
            model_attribute(self.env['account.move.line'].sudo(), '_read_group')(
                [
                    ('construction_boq_component_id', 'in', materials.ids),
                    ('parent_state', '=', 'posted'),
                    ('account_id.internal_group', '=', 'expense'),
                    ('purchase_line_id', '=', False),
                    '|',
                    ('product_id', '=', False),
                    ('product_id.is_storable', '=', False),
                ],
                ['construction_boq_component_id'],
                ['balance:sum'],
            )
        )
        for project in materials.project_id:
            costs, _unallocated = model_attribute(project, '_get_material_actual_costs')()
            for component in materials.filtered(lambda c, p=project: c.project_id == p):
                component.actual_cost = costs.get(component.id, 0.0) + manual.get(component, 0.0)
                component.cost_variance = component.effective_cost - component.actual_cost

    def action_view_material_requests(self):
        """View material requests."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Material Requests of %s', self.display_name),
            'res_model': 'construction.material.request.line',
            'view_mode': 'list',
            'views': [
                (
                    self.env.ref(
                        'construction_management.view_construction_material_request_line_boq_list'
                    ).id,
                    'list',
                )
            ],
            'domain': [
                ('project_id', '=', self.project_id.id),
                ('product_id', '=', self.product_id.id),
            ],
            'context': {'create': False},
        }

    def action_view_subcontract_lines(self):
        """View subcontract lines."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Subcontracts of %s', self.display_name),
            'res_model': 'construction.subcontract.line',
            'view_mode': 'list',
            'views': [
                (
                    self.env.ref(
                        'construction_management.view_construction_subcontract_line_boq_list'
                    ).id,
                    'list',
                )
            ],
            'domain': [('boq_item_id', '=', self.item_id.id)],
            'context': {'create': False},
        }
