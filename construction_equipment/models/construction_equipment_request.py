"""Construction equipment construction equipment request support."""

from odoo import _, fields, models
from odoo.exceptions import UserError


class ConstructionEquipmentRequest(models.Model):
    """Construction Equipment Request."""

    _inherit = 'construction.equipment.request'
    movement_id = fields.Many2one(
        'construction.equipment.movement', string='Movement', readonly=True, copy=False
    )
    return_movement_id = fields.Many2one(
        'construction.equipment.movement', string='Return Movement', readonly=True, copy=False
    )

    def _dispatch_equipment(self, equipment):
        """The equipment travels to the site through a movement confirmed by the
        transportation manager."""
        self.ensure_one()
        movement = self.env['construction.equipment.movement'].create(
            {
                'equipment_id': equipment.id,
                'to_project_id': self.project_id.id,
                'move_datetime': fields.Datetime.now(),
                'request_id': self.id,
            }
        )
        self.movement_id = movement

    def _place_rented_equipment(self, equipment):
        self.ensure_one()
        movement = self.env['construction.equipment.movement'].create(
            {
                'equipment_id': equipment.id,
                'from_project_id': equipment.current_project_id.id,
                'to_project_id': self.project_id.id,
                'move_datetime': fields.Datetime.now(),
                'request_id': self.id,
            }
        )
        movement.sudo().with_context(construction_skip_inventory=True).action_done()
        if movement.state == 'in_transit':
            movement.action_confirm_arrival()
        self.movement_id = movement

    def _recall_equipment(self):
        """Cancel the movement before the equipment arrives on site."""
        self.ensure_one()
        movement = self.movement_id
        if movement.state == 'done':
            raise UserError(
                _(
                    (
                        'Equipment %s has already arrived on site. Release '
                        'the request to send it back.'
                    ),
                    self.equipment_id.display_name,
                )
            )
        if movement.state in ('draft', 'in_transit'):
            movement.action_cancel()
        self.movement_id = False

    def _check_can_release(self):
        res = super()._check_can_release()
        for request in self:
            if request.state == 'assigned' and request.movement_id.state in ('draft', 'in_transit'):
                raise UserError(
                    _(
                        (
                            'The equipment has not arrived on site yet: unassign '
                            'the request instead.'
                        )
                    )
                )
        return res

    def _return_equipment(self, equipment):
        """Prepare a draft return movement to the main yard for the transportation manager."""
        self.ensure_one()
        if equipment.movement_ids.filtered(lambda m: m.state in ('draft', 'in_transit')):
            return
        self.return_movement_id = self.env['construction.equipment.movement'].create(
            {
                'equipment_id': equipment.id,
                'from_project_id': self.project_id.id,
                'to_project_id': False,
                'request_id': self.id,
            }
        )

    def action_view_return_movement(self):
        """Action view return movement."""
        self.ensure_one()
        movement = self.return_movement_id or self.movement_id
        if not movement:
            raise UserError(_('No movement is linked to this request.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'construction.equipment.movement',
            'res_id': movement.id,
            'view_mode': 'form',
        }
