"""Purchase order line construction boq consumption for construction management."""

from odoo import fields
from odoo import models

from .construction_common import material_line_field


class PurchaseOrderLine(models.Model):
    """Purchase order line."""

    _inherit = 'purchase.order.line'

    construction_material_line_id = material_line_field()
    construction_boq_component_id = fields.Many2one(
        related='construction_material_line_id.boq_component_id', store=True, string='BOQ Material'
    )
    construction_boq_item_id = fields.Many2one(
        related='construction_material_line_id.boq_item_id', store=True, string='BOQ Item'
    )

    def _prepare_account_move_line(self, move=False):
        """Bills of the purchase orders of material requests are charged to the BOQ item (consumable
        materials; stored materials are valued when delivered to the site).
        """
        res = super()._prepare_account_move_line(move=move)
        if self.construction_material_line_id:
            res.setdefault('construction_cost_type', 'material')
            if self.construction_boq_component_id:
                res.setdefault(
                    'construction_boq_component_id', self.construction_boq_component_id.id
                )
                res.setdefault('construction_boq_item_id', self.construction_boq_item_id.id)
        return res
