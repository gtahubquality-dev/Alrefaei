"""Construction equipment construction boq component support."""

from collections import defaultdict
from odoo import models
from .runtime import call_method


class ConstructionBoqComponent(models.Model):
    """Construction Boq Component."""

    _inherit = 'construction.boq.component'

    def _compute_actual_cost(self):
        """Rented equipment: hours worked and not billed yet are costed at the rental price."""
        super()._compute_actual_cost()
        equipment = self.filtered(lambda c: c.component_type == 'equipment' and c.id)
        if not equipment:
            return
        requests = (
            self.env['construction.equipment.request']
            .sudo()
            .search(
                [
                    ('boq_component_id', 'in', equipment.ids),
                    ('state', 'in', ('assigned', 'rental', 'done')),
                ]
            )
        )
        accruals = call_method(requests, '_get_rental_accruals')
        by_component = defaultdict(float)
        for request in requests.filtered(lambda r: r.id in accruals):
            by_component[request.boq_component_id.id] += accruals[request.id]
        for component in equipment.filtered(lambda c: c.id in by_component):
            component.actual_cost += by_component[component.id]
            component.cost_variance = component.effective_cost - component.actual_cost
