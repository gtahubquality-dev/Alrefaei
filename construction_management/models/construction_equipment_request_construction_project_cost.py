"""Construction equipment request construction project cost for construction management."""

from collections import defaultdict
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from .construction_project_cost import COST_REQUEST_STATES

from .runtime import model_attribute


class ConstructionEquipmentRequest(models.Model):
    """Construction equipment request."""

    _inherit = 'construction.equipment.request'

    planned_cost = fields.Monetary(
        compute='_compute_costs',
        string='Planned Cost',
        help="Requested quantity at the unit cost of the BOQ equipment.",
    )
    committed_cost = fields.Monetary(
        compute='_compute_costs',
        string='Ordered, not Billed',
        help="Confirmed rental purchase orders not billed yet.",
    )
    actual_cost = fields.Monetary(
        compute='_compute_costs',
        string='Actual Cost',
        help=(
            "Costs charged to the request: usage of company equipment, expenses on site and rental"
            " bills, plus the rented hours worked and not billed yet (at the rental price)."
        ),
    )
    cost_variance = fields.Monetary(compute='_compute_costs', string='Variance vs Plan')
    consumed_quantity = fields.Float(
        compute='_compute_consumed_quantity',
        string='Consumed Quantity',
        digits='Product Unit',
        help=(
            "Hours worked under this request (posted operating hours of the company equipment) and"
            " hours billed by the rental vendor, in the unit of the BOQ equipment."
        ),
    )
    unconsumed_quantity = fields.Float(
        compute='_compute_consumed_quantity',
        string='Requested, not Consumed',
        digits='Product Unit',
    )

    def _consumption_uom(self):
        self.ensure_one()
        return self.boq_component_id.uom_id or self.env.ref('uom.product_uom_hour')

    def _get_consumed_quantities(self):
        """{request id: consumed quantity in the unit of the BOQ equipment}. Here: the quantities
        billed by the rental vendors (posted bills of the rental purchase orders); the equipment
        module adds the operating hours of the company equipment.
        """
        consumed = defaultdict(float)
        if not self.ids:
            return consumed
        lines = (
            self.env['account.move.line']
            .sudo()
            .search(
                [
                    ('construction_equipment_request_id', 'in', self.ids),
                    ('parent_state', '=', 'posted'),
                    ('purchase_line_id', '!=', False),
                    ('display_type', '=', 'product'),
                ]
            )
        )
        for line in lines:
            request = line.construction_equipment_request_id
            quantity = line.quantity
            if line.product_uom_id:
                quantity = model_attribute(line.product_uom_id, '_compute_quantity')(
                    quantity, model_attribute(request, '_consumption_uom')(), raise_if_failure=False
                )
            sign = -1.0 if line.move_id.move_type == 'in_refund' else 1.0
            consumed[request.id] += sign * quantity
        return consumed

    @api.depends('requested_quantity', 'state')
    def _compute_consumed_quantity(self):
        consumed = self._get_consumed_quantities()
        for request in self:
            request.consumed_quantity = consumed.get(request.id, 0.0)
            request.unconsumed_quantity = request.requested_quantity - request.consumed_quantity

    @api.model
    def _get_active_request(self, equipment, project, date):
        """Request under which ``equipment`` works on ``project`` at ``date`` (its costs are charged
        to it)."""
        if not equipment or not project:
            return self.browse()
        domain = [
            ('project_id', '=', project.id),
            ('state', 'in', COST_REQUEST_STATES),
            '|',
            ('equipment_id', '=', equipment.id),
            ('rented_equipment_id', '=', equipment.id),
        ]
        request_model = self.sudo()
        if date:
            request = request_model.search(
                domain
                + [
                    ('date_from', '<=', date),
                    '|',
                    ('date_to', '=', False),
                    ('date_to', '>=', date),
                ],
                order='date_from desc, id desc',
                limit=1,
            )
            if request:
                return request
        return request_model.search(domain, order='date_from desc, id desc', limit=1)

    def _get_cost_line_values(self):
        """Values of the journal items that charge a cost to this request (and to its BOQ
        equipment)."""
        self.ensure_one()
        return {
            'construction_cost_type': 'equipment',
            'construction_equipment_request_id': self.id,
            'construction_boq_component_id': self.boq_component_id.id,
            'construction_boq_item_id': self.boq_item_id.id,
        }

    def _get_actual_costs(self):
        """{request id: posted cost} from the journal items charged to the requests."""
        if not self.ids:
            return {}
        groups = model_attribute(self.env['account.move.line'].sudo(), '_read_group')(
            [
                ('construction_equipment_request_id', 'in', self.ids),
                ('parent_state', '=', 'posted'),
                ('account_id.internal_group', '=', 'expense'),
            ],
            ['construction_equipment_request_id'],
            ['balance:sum'],
        )
        return {request.id: balance for request, balance in groups}

    def _get_committed_costs(self):
        """{request id: confirmed rental purchase amounts not billed yet}."""
        committed = defaultdict(float)
        if not self.ids:
            return committed
        lines = (
            self.env['purchase.order.line']
            .sudo()
            .search(
                [
                    ('order_id.state', 'in', ('purchase', 'done')),
                    ('display_type', '=', False),
                    '|',
                    ('order_id.construction_equipment_request_id', 'in', self.ids),
                    ('order_id.construction_equipment_rental_id.request_id', 'in', self.ids),
                ]
            )
        )
        for line in lines:
            order = line.order_id
            request = (
                order.construction_equipment_request_id
                or order.construction_equipment_rental_id.request_id
            )
            to_bill = max(line.product_qty - line.qty_invoiced, 0.0)
            committed[request.id] += model_attribute(order.currency_id, '_convert')(
                to_bill * line.price_unit * (1 - (line.discount or 0.0) / 100.0),
                order.company_id.currency_id,
                order.company_id,
                order.date_order or fields.Date.today(),
            )
        return committed

    @api.depends('requested_quantity', 'boq_component_id.unit_cost', 'state')
    def _compute_costs(self):
        actual = self._get_actual_costs()
        committed = self._get_committed_costs()
        for request in self:
            request.planned_cost = request.requested_quantity * request.boq_component_id.unit_cost
            request.actual_cost = actual.get(request.id, 0.0)
            request.committed_cost = committed.get(request.id, 0.0)
            request.cost_variance = (
                request.planned_cost - request.actual_cost - request.committed_cost
            )

    def action_view_cost_lines(self):
        """View cost lines."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Costs of %s', self.name),
            'res_model': 'account.move.line',
            'view_mode': 'list,pivot',
            'domain': [
                ('construction_equipment_request_id', '=', self.id),
                ('parent_state', '=', 'posted'),
                ('account_id.internal_group', '=', 'expense'),
            ],
            'context': {'create': False},
        }
