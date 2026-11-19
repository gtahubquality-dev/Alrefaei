"""Construction project construction boq consumption for construction management."""

from collections import defaultdict
from odoo import models

from .boq_consumption_common import (
    done_stock_moves,
    site_stock_move_domain,
    site_stock_move_sign,
    site_stock_move_value,
)
from .runtime import model_attribute


class ConstructionProject(models.Model):
    """Construction project."""

    _inherit = 'construction.project'

    def _get_material_site_moves(self, product_ids):
        """[(move, sign)] of the done moves of the products into the project warehouse (+1) and out
        of it to other warehouses or vendors (-1, returns). Consumptions on site stay delivered.
        """
        self.ensure_one()
        warehouse = self.warehouse_id
        if not warehouse or not warehouse.view_location_id or not product_ids:
            return []
        view = warehouse.view_location_id
        prefix = view.parent_path
        moves = done_stock_moves(
            self.env,
            [
                ('product_id', 'in', product_ids),
                ('company_id', '=', self.company_id.id),
                *site_stock_move_domain(view),
            ],
        )
        result = []
        for move in moves:
            sign = site_stock_move_sign(move, prefix, ('internal', 'transit', 'supplier'))
            if sign:
                result.append((move, sign))
        return result

    def _get_material_bill_domain(self, date_from=False, date_to=False):
        """Posted vendor bill lines of the materials purchased for the project (rentals
        excluded)."""
        self.ensure_one()
        domain = [
            ('parent_state', '=', 'posted'),
            ('display_type', '=', 'product'),
            ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ('product_id.type', '=', 'consu'),
            ('purchase_line_id.order_id.construction_equipment_rental_id', '=', False),
            ('purchase_line_id.order_id.construction_equipment_request_id', '=', False),
        ]
        if self.warehouse_id:
            domain += [
                '|',
                ('purchase_line_id.order_id.construction_project_id', '=', self.id),
                (
                    'purchase_line_id.order_id.picking_type_id.warehouse_id',
                    '=',
                    self.warehouse_id.id,
                ),
            ]
        else:
            domain.append(('purchase_line_id.order_id.construction_project_id', '=', self.id))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain

    def _get_material_actual_costs(self, date_from=False, date_to=False):
        """({material component id: cost}, {product: cost charged to no BOQ item}).

        * purchases: posted vendor bills (credit notes deducted), at the billed amounts;
        * transfers from the other warehouses of the company: value of the delivered quantities (net
        of the
          returns).
        Costs of a request line for a given BOQ item go to it; the others are shared over the BOQ
        items using
        the material in proportion to their BOQ quantities (as their quantities are)."""
        self.ensure_one()
        linked = defaultdict(float)
        rest = defaultdict(float)
        for line in (
            self.env['account.move.line']
            .sudo()
            .search(self._get_material_bill_domain(date_from, date_to))
        ):
            component = line.purchase_line_id.construction_boq_component_id
            if component:
                linked[component.id] += line.balance
            else:
                rest[line.product_id] += line.balance
        for move, sign, value in self._get_material_transfer_values(date_from, date_to):
            origin = move.origin_returned_move_id or move
            component = origin.construction_material_line_id.boq_component_id
            if component:
                linked[component.id] += sign * value
            else:
                rest[move.product_id] += sign * value
        components = self.sudo().boq_item_ids.component_ids.filtered(
            lambda c: c.component_type == 'material' and c.product_id
        )

        requirement_model = self.env['construction.material.requirement']
        shares = {}
        for product in rest:
            product_components = components.filtered(lambda c, p=product: c.product_id == p)
            weights = {
                c.id: max(
                    model_attribute(requirement_model, '_convert')(
                        c.effective_quantity, c.uom_id, c.product_id
                    ),
                    0.0,
                )
                for c in product_components
            }
            total = sum(weights.values())
            for component_id, weight in weights.items():
                shares[component_id] = weight / total if total else 0.0
        costs = defaultdict(float, linked)
        unallocated = defaultdict(float)
        for product, cost in rest.items():
            product_components = components.filtered(lambda c, p=product: c.product_id == p)
            allocated = 0.0
            for component in product_components:
                share = shares.get(component.id, 0.0)
                costs[component.id] += cost * share
                allocated += share
            if not allocated:
                unallocated[product] += cost
        for component_id in list(costs):
            if component_id not in components.ids:
                component = self.env['construction.boq.component'].browse(component_id)
                unallocated[component.product_id] += costs.pop(component_id)
        return costs, unallocated

    def _get_material_transfer_values(self, date_from=False, date_to=False):
        """[(move, sign, value)] of the stored materials transferred to the project warehouse from
        the other warehouses (+1) or sent back (-1). Receipts from vendors and their returns are
        costed by the bills.
        """
        self.ensure_one()
        warehouse = self.warehouse_id
        if not warehouse or not warehouse.view_location_id:
            return []
        view = warehouse.view_location_id

        products = (
            self.sudo()
            .boq_item_ids.component_ids.filtered(lambda c: c.component_type == 'material')
            .product_id
            | self.sudo().material_requirement_ids.product_id
        )
        if 'product_id' in self.env['construction.equipment']._fields:
            products -= (
                self.env['construction.equipment']
                .sudo()
                .with_context(active_test=False)
                .search([('product_id', 'in', products.ids)])
                .product_id
            )
        if not products:
            return []
        domain = [
            ('product_id', 'in', products.ids),
            ('product_id.is_storable', '=', True),
            ('company_id', '=', self.company_id.id),
            ('location_id.usage', '!=', 'supplier'),
            ('location_dest_id.usage', '!=', 'supplier'),
            *site_stock_move_domain(view, date_from, date_to),
        ]
        prefix = view.parent_path
        result = []
        for move in done_stock_moves(self.env, domain):
            if move.purchase_line_id or move.origin_returned_move_id.purchase_line_id:
                continue
            sign = site_stock_move_sign(move, prefix, ('internal', 'transit'))
            if sign:
                result.append((move, sign, site_stock_move_value(move, self)))
        return result

    def _get_material_cost_shares(self):
        """{material component id: share of the delivered cost of its product}: by delivered
        quantities, or by BOQ quantities when nothing was delivered.
        """
        self.ensure_one()
        requirement_model = self.env['construction.material.requirement']
        components = self.sudo().boq_item_ids.component_ids.filtered(
            lambda c: c.component_type == 'material' and c.product_id
        )
        consumption = (
            model_attribute(components, '_get_material_consumption')() if components else {}
        )
        delivered, planned = {}, {}
        for component in components:
            delivered[component.id] = model_attribute(requirement_model, '_convert')(
                consumption.get(component.id, (0.0, 0.0))[1], component.uom_id, component.product_id
            )
            planned[component.id] = model_attribute(requirement_model, '_convert')(
                component.effective_quantity, component.uom_id, component.product_id
            )
        shares = {}
        for product in components.product_id:
            product_components = components.filtered(lambda c, p=product: c.product_id == p)
            weights = (
                delivered
                if sum(max(delivered[c.id], 0.0) for c in product_components) > 0
                else planned
            )
            total = sum(max(weights[c.id], 0.0) for c in product_components)
            for component in product_components:
                shares[component.id] = max(weights[component.id], 0.0) / total if total else 0.0
        return shares
