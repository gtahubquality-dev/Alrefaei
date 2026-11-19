"""Construction equipment stock picking support."""

from odoo import fields, models
from .runtime import call_method


class StockPicking(models.Model):
    """Stock Picking."""

    _inherit = 'stock.picking'
    construction_equipment_movement_id = fields.Many2one(
        'construction.equipment.movement', string='Equipment Movement', readonly=True, copy=False
    )

    def _action_done(self):
        res = super()._action_done()
        movements = self.sudo().construction_equipment_movement_id.filtered(
            lambda m: m.state == 'in_transit'
        )
        call_method(movements.filtered(lambda m: m.picking_id.state == 'done'), '_finalize')
        return res

    def action_cancel(self):
        """Action cancel."""
        res = super().action_cancel()
        for picking in self.filtered(lambda p: p.state == 'cancel').sudo():
            movement = picking.construction_equipment_movement_id
            if movement.state == 'in_transit' and movement.picking_id == picking:
                call_method(movement, '_cancel_from_transfer')
        return res
