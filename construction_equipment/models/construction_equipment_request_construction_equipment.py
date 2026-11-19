"""Construction equipment construction equipment request construction equipment support."""

from odoo import _, fields, models
from .runtime import call_method


class ConstructionEquipmentRequest(models.Model):
    """Construction Equipment Request."""

    _inherit = 'construction.equipment.request'
    usage_ids = fields.One2many(
        'construction.equipment.usage', 'request_id', string='Operating Hours'
    )

    def _get_consumed_quantities(self):
        """Posted operating hours of the equipment (company owned or rented). A rented
        equipment whose hours are both logged and billed by the vendor is consumed once:
        the larger of the two quantities."""
        billed = super()._get_consumed_quantities()
        if not self.ids:
            return billed
        hour = self.env.ref('uom.product_uom_hour')
        groups = call_method(
            self.env['construction.equipment.usage'].sudo(),
            '_read_group',
            [('request_id', 'in', self.ids), ('state', '=', 'posted')],
            ['request_id'],
            ['hours:sum'],
        )
        logged = {
            request.id: call_method(
                hour,
                '_compute_quantity',
                hours,
                call_method(request, '_consumption_uom'),
                raise_if_failure=False,
            )
            for (request, hours) in groups
        }
        consumed = type(billed)(float) if hasattr(billed, 'default_factory') else {}
        for request_id in set(billed) | set(logged):
            consumed[request_id] = max(billed.get(request_id, 0.0), logged.get(request_id, 0.0))
        return consumed

    def _get_rental_accruals(self):
        """{request id: cost of the operating hours of a rented equipment not billed yet by
        the vendor, at the rental price}: the hours worked are a cost of the project
        before the vendor bill."""
        rentals = self.filtered(lambda r: r.id and r.rented_equipment_id and r.rental_price)
        if not rentals:
            return {}
        billed = super(ConstructionEquipmentRequest, rentals)._get_consumed_quantities()
        hour = self.env.ref('uom.product_uom_hour')
        groups = call_method(
            self.env['construction.equipment.usage'].sudo(),
            '_read_group',
            [('request_id', 'in', rentals.ids), ('state', '=', 'posted')],
            ['request_id'],
            ['hours:sum'],
        )
        accruals = {}
        for request, hours in groups:
            uom = call_method(request, '_consumption_uom')
            unbilled = call_method(
                hour, '_compute_quantity', hours, uom, raise_if_failure=False
            ) - billed.get(request.id, 0.0)
            if unbilled > 0:
                rental_uom = request.rental_product_id.uom_id
                quantity = (
                    call_method(
                        uom, '_compute_quantity', unbilled, rental_uom, raise_if_failure=False
                    )
                    if rental_uom
                    else unbilled
                )
                accruals[request.id] = quantity * request.rental_price
        return accruals

    def _get_actual_costs(self):
        actual = super()._get_actual_costs()
        for request_id, amount in self._get_rental_accruals().items():
            actual[request_id] = actual.get(request_id, 0.0) + amount
        return actual

    def action_view_usage(self):
        """Action view usage."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Operating Hours - %s', self.name),
            'res_model': 'construction.equipment.usage',
            'view_mode': 'list,form',
            'domain': [('request_id', '=', self.id)],
            'context': {
                'default_request_id': self.id,
                'default_project_id': self.project_id.id,
                'default_equipment_id': self.equipment_id.id,
            },
        }
