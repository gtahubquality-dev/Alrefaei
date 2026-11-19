"""Purchase order line for construction management."""

from odoo import api
from odoo import models

from .runtime import model_attribute


class PurchaseOrderLine(models.Model):
    """Purchase order line."""

    _inherit = 'purchase.order.line'

    def _prepare_account_move_line(self, move=False):
        """Rental bills of an equipment request are charged to the request and its BOQ equipment."""
        res = super()._prepare_account_move_line(move=move)
        order = self.order_id
        request = (
            order.construction_equipment_request_id
            or order.construction_equipment_rental_id.request_id
        )
        if order.construction_equipment_request_id or order.construction_equipment_rental_id:
            res.update(
                model_attribute(request, '_get_cost_line_values')()
                if request
                else {'construction_cost_type': 'equipment'}
            )
        return res

    def _compute_analytic_distribution(self):
        res = super()._compute_analytic_distribution()
        for line in self:
            project = line.order_id.construction_project_id
            if not line.display_type and project and not line.analytic_distribution:
                line.analytic_distribution = model_attribute(
                    project, '_get_analytic_distribution'
                )()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        lines = super().create(vals_list)
        model_attribute(
            lines.order_id.filtered(lambda o: o.state in ('purchase', 'done')),
            '_check_construction_boq_limits',
        )()
        return lines

    def write(self, vals):
        """Write."""
        res = super().write(vals)
        if {'product_qty', 'product_id', 'product_uom_id'}.intersection(vals):
            model_attribute(
                self.order_id.filtered(lambda o: o.state in ('purchase', 'done')),
                '_check_construction_boq_limits',
            )()
        return res
