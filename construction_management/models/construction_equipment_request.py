"""Construction equipment request for construction management."""

from odoo import _
from odoo import fields
from odoo import models

from .runtime import model_attribute


class ConstructionEquipmentRequest(models.Model):
    """Construction equipment request."""

    _inherit = 'construction.equipment.request'

    rental_contract_id = fields.Many2one(
        'construction.equipment.rental', string='Rental Contract', readonly=True, copy=False
    )

    def _create_rental_contract(self, order):
        """Rental contract created when the transportation manager rents the requested equipment
        externally."""
        self.ensure_one()
        rental = (
            self.env['construction.equipment.rental']
            .sudo()
            .create(
                {
                    'company_id': self.company_id.id,
                    'partner_id': self.rental_vendor_id.id,
                    'equipment_id': self.rented_equipment_id.id,
                    'project_id': self.project_id.id,
                    'request_id': self.id,
                    'date_start': self.date_from or fields.Date.context_today(self),
                    'date_end': self.date_to,
                    'product_id': self.rental_product_id.id,
                    'quantity': self.rental_quantity,
                    'unit_price': self.rental_price,
                    'state': 'running' if self.rented_equipment_id else 'draft',
                }
            )
        )

        order.sudo().construction_equipment_rental_id = rental
        model_attribute(rental, '_sync_equipment')()
        self.rental_contract_id = rental
        return rental

    def action_request_rental(self):
        """Request rental."""
        res = super().action_request_rental()
        for request in self.filtered(
            lambda r: r.state == 'rental' and r.purchase_order_id and not r.rental_contract_id
        ):
            model_attribute(request, '_create_rental_contract')(request.purchase_order_id)
        return res

    def action_extend_rental(self):
        """Extend rental."""
        quantities = {request.id: request.rental_extension_qty for request in self}
        res = super().action_extend_rental()
        for request in self.filtered('rental_contract_id'):
            rental = request.rental_contract_id.sudo()
            rental.quantity += quantities.get(request.id, 0.0)
            for order in request.sudo().rental_order_ids.filtered(
                lambda o: not o.construction_equipment_rental_id
            ):
                order.construction_equipment_rental_id = rental
        return res

    def action_release(self):
        """Release."""
        rentals = self.filtered(lambda r: r.state == 'rental').rental_contract_id
        res = super().action_release()
        if not (self.env.su and self.env.context.get('construction_rental_return')):
            for rental in rentals.filtered(lambda r: r.state == 'running'):
                rental.message_post(
                    body=_(
                        'Equipment request %s released: return the equipment to the vendor to '
                        'close the rental.',
                        rental.request_id.name,
                    )
                )
        return res

    def _reopen_after_rental_cancel(self, order):
        res = super()._reopen_after_rental_cancel(order)
        model_attribute(order.construction_equipment_rental_id, '_cancel_from_purchase')(order)
        return res
