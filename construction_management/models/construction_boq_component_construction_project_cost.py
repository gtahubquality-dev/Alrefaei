"""Construction boq component construction project cost for construction management."""

from collections import defaultdict
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from .construction_project_cost import REQUESTED_STATES

from .runtime import model_attribute


class ConstructionBoqComponent(models.Model):
    """Construction boq component."""

    _inherit = 'construction.boq.component'

    actual_cost = fields.Monetary(
        compute='_compute_actual_cost',
        string='Actual Cost',
        help=(
            "Operational actual cost of the component: materials from the posted vendor bills and"
            " transfers, equipment hours (rented hours not billed yet at the rental price),"
            " subcontracted works approved by the site at the contract price, labor posted. The"
            " Cost & Revenue report shows the posted entries only."
        ),
    )
    cost_variance = fields.Monetary(compute='_compute_actual_cost', string='Variance')
    requested_quantity = fields.Float(
        compute='_compute_consumption',
        string='Requested',
        digits='Product Unit',
        help="Quantity requested by the active equipment requests of this BOQ equipment.",
    )
    consumed_quantity = fields.Float(
        compute='_compute_consumption',
        string='Consumed',
        digits='Product Unit',
        help=(
            "Hours actually worked on the project for this BOQ equipment: posted operating hours of"
            " the company equipment and hours billed by the rental vendors."
        ),
    )
    remaining_consumption = fields.Float(
        compute='_compute_consumption',
        string='Remaining',
        digits='Product Unit',
        help=(
            "BOQ quantity (change orders included) not consumed yet. Negative: the BOQ quantity is"
            " exceeded."
        ),
    )
    consumption_percent = fields.Float(compute='_compute_consumption', string='Consumed (%)')

    @api.depends(
        'effective_quantity', 'quantity', 'component_type', 'product_id', 'uom_id', 'item_id'
    )
    def _compute_consumption(self):
        equipment = self.filtered(lambda c: c.component_type == 'equipment' and c.id)
        requests = (
            self.env['construction.equipment.request']
            .sudo()
            .search([('boq_component_id', 'in', equipment.ids), ('state', 'in', REQUESTED_STATES)])
            if equipment
            else self.env['construction.equipment.request']
        )
        consumed = model_attribute(requests, '_get_consumed_quantities')()
        requested = defaultdict(float)
        used = defaultdict(float)
        for request in requests:
            requested[request.boq_component_id.id] += request.requested_quantity
            used[request.boq_component_id.id] += consumed.get(request.id, 0.0)
        for component in self:
            component.requested_quantity = requested.get(component.id, 0.0)
            component.consumed_quantity = used.get(component.id, 0.0)
            component.remaining_consumption = (
                component.effective_quantity - component.consumed_quantity
            )
            component.consumption_percent = (
                component.consumed_quantity / component.effective_quantity * 100.0
                if component.effective_quantity
                else 0.0
            )

    def action_view_equipment_requests(self):
        """View equipment requests."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Requests of %s', self.display_name),
            'res_model': 'construction.equipment.request',
            'view_mode': 'list,form',
            'domain': [('boq_component_id', '=', self.id)],
            'context': {'create': False},
        }

    @api.depends('effective_cost', 'component_type')
    def _compute_actual_cost(self):
        groups = (
            model_attribute(self.env['account.move.line'].sudo(), '_read_group')(
                [
                    ('construction_boq_component_id', 'in', self.ids),
                    ('parent_state', '=', 'posted'),
                    ('account_id.internal_group', '=', 'expense'),
                    '|',
                    ('product_id', '=', False),
                    ('product_id.is_storable', '=', False),
                ],
                ['construction_boq_component_id'],
                ['balance:sum'],
            )
            if self.ids
            else []
        )
        actual = {component.id: balance for component, balance in groups}
        for component in self:
            component.actual_cost = actual.get(component.id, 0.0)
            component.cost_variance = component.effective_cost - component.actual_cost
