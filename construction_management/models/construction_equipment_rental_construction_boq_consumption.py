"""Construction equipment rental construction boq consumption for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .runtime import model_attribute


class ConstructionEquipmentRental(models.Model):
    """Every rental contract of a project is charged to an equipment of the BOQ: through the
    equipment request it was made for, or through the request created for it when it starts. Its
    operating hours, rental bills and costs are then consumed from the BOQ like those of any
    equipment request.
    """

    _inherit = 'construction.equipment.rental'

    boq_component_id = fields.Many2one(
        'construction.boq.component',
        string='BOQ Equipment',
        index='btree_not_null',
        tracking=True,
        compute='_compute_boq_component_id',
        store=True,
        readonly=False,
        precompute=True,
        domain="[('project_id', '=', project_id), ('component_type', '=', 'equipment')]",
        help=(
            "Equipment of the BOQ this rental is consumed from (required to start the rental of a"
            " project)."
        ),
    )
    boq_item_id = fields.Many2one(related='boq_component_id.item_id', store=True, string='BOQ Item')
    boq_uom_id = fields.Many2one(related='boq_component_id.uom_id', string='BOQ Unit')
    boq_quantity = fields.Float(
        related='boq_component_id.effective_quantity', string='BOQ Quantity'
    )
    boq_consumed_quantity = fields.Float(
        related='boq_component_id.consumed_quantity', string='Consumed in BOQ'
    )
    boq_consumption_percent = fields.Float(
        related='boq_component_id.consumption_percent', string='BOQ Consumed (%)'
    )
    consumed_quantity = fields.Float(
        related='request_id.consumed_quantity',
        string='Consumed by this Rental',
        help=(
            "Operating hours of the rented equipment and quantities billed by the vendor, in the"
            " BOQ unit."
        ),
    )
    actual_cost = fields.Monetary(related='request_id.actual_cost', string='Actual Cost')

    @api.depends('request_id.boq_component_id', 'project_id')
    def _compute_boq_component_id(self):
        for rental in self:
            if rental.request_id.boq_component_id:
                rental.boq_component_id = rental.request_id.boq_component_id
            elif rental.boq_component_id.project_id != rental.project_id:
                rental.boq_component_id = False
            else:
                rental.boq_component_id = rental.boq_component_id

    @api.constrains('boq_component_id', 'project_id')
    def _check_boq_component(self):
        for rental in self.filtered('boq_component_id'):
            component = rental.boq_component_id
            if component.project_id != rental.project_id or component.component_type != 'equipment':
                raise ValidationError(
                    _(
                        'Please select an equipment of the BOQ of project %s.',
                        rental.project_id.display_name,
                    )
                )

    def write(self, vals):
        """Write."""
        res = super().write(vals)
        if 'boq_component_id' in vals and not (
            self.env.su and self.env.context.get('construction_rental_sync')
        ):
            for rental in self.filtered(
                lambda r: r.request_id
                and r.boq_component_id
                and r.request_id.boq_component_id != r.boq_component_id
            ):
                rental.request_id.sudo().boq_component_id = rental.boq_component_id

            model_attribute(
                self.filtered(
                    lambda r: r.state == 'running'
                    and r.project_id
                    and r.boq_component_id
                    and not r.request_id
                ),
                '_ensure_boq_request',
            )()
        return res

    def _requested_boq_quantity(self, quantity):
        """Rental quantity in the unit of the BOQ equipment (unchanged when the units do not
        convert)."""
        self.ensure_one()
        uom = self.product_id.uom_id
        if not uom or not self.boq_component_id.uom_id:
            return quantity
        return model_attribute(uom, '_compute_quantity')(
            quantity, self.boq_component_id.uom_id, raise_if_failure=False
        )

    def _ensure_boq_request(self):
        """Rentals of a project made directly (not from an equipment request): create the equipment
        request that charges them to the BOQ (operating hours, rental bills, costs). The BOQ
        quantity is checked like for any request: beyond it, only Senior Management can rent.
        """
        request_model = self.env['construction.equipment.request'].sudo()
        for rental in self.filtered(lambda r: r.project_id and not r.request_id):
            if not rental.boq_component_id:
                raise UserError(
                    _(
                        'Please select the BOQ equipment of project %(project)s that rental'
                        ' %(rental)s is consumed from.',
                        project=rental.project_id.display_name,
                        rental=rental.name,
                    )
                )
            is_manager = self.env.user.has_group(
                'construction_management.group_construction_manager'
            )
            orders = rental.sudo().purchase_order_ids.filtered(lambda o: o.state != 'cancel')
            component = rental.boq_component_id
            others = request_model.search(
                [
                    ('boq_component_id', '=', component.id),
                    ('state', 'in', ('to_approve', 'submitted', 'assigned', 'rental', 'done')),
                ]
            )
            available = component.effective_quantity - sum(others.mapped('requested_quantity'))
            exceeds = (
                float_compare(
                    model_attribute(rental, '_requested_boq_quantity')(rental.quantity),
                    available,
                    precision_digits=4,
                )
                > 0
            )
            if exceeds and not is_manager:
                raise UserError(
                    _(
                        'Rental %(rental)s exceeds the quantity of the BOQ equipment %(equipment)s'
                        ' still available: only Senior Management can start it.',
                        rental=rental.name,
                        equipment=rental.boq_component_id.display_name,
                    )
                )
            request = request_model.create(
                {
                    'project_id': rental.project_id.id,
                    'description': (
                        rental.equipment_id.display_name
                        or rental.product_id.display_name
                        or rental.name
                    ),
                    'date_from': rental.date_start,
                    'date_to': rental.date_end,
                    'boq_component_id': rental.boq_component_id.id,
                    'requested_quantity': model_attribute(rental, '_requested_boq_quantity')(
                        rental.quantity
                    ),
                    'requested_by_id': self.env.user.id,
                    'rental_vendor_id': rental.partner_id.id,
                    'rental_product_id': rental.product_id.id,
                    'rental_quantity': rental.quantity,
                    'rental_price': rental.unit_price,
                    'rented_equipment_id': rental.equipment_id.id,
                    'purchase_order_id': orders[-1:].id,
                    'rental_contract_id': rental.id,
                    'exceeds_boq': exceeds,
                    'approved_by_id': self.env.user.id if is_manager else False,
                    'approved_date': fields.Datetime.now() if is_manager else False,
                    'note': _('Created for rental contract %s.', rental.name),
                    'state': 'rental',
                }
            )
            orders.write({'construction_equipment_request_id': request.id})
            rental.sudo().with_context(construction_rental_sync=True).request_id = request
            rental.message_post(
                body=_(
                    'Charged to the BOQ equipment %(equipment)s through equipment request '
                    '%(request)s.',
                    equipment=rental.boq_component_id.display_name,
                    request=model_attribute(request, '_get_html_link')(),
                )
            )

    def action_create_purchase_order(self):
        """Create purchase order."""
        model_attribute(self.filtered(lambda r: r.state == 'running'), '_ensure_boq_request')()
        res = super().action_create_purchase_order()
        for rental in self.filtered(lambda r: r.request_id and not r.request_id.purchase_order_id):
            rental.request_id.sudo().purchase_order_id = rental.sudo().purchase_order_ids.filtered(
                lambda o: o.state != 'cancel'
            )[-1:]
        return res

    def action_start(self):
        """Start."""
        self._check_transport_manager()
        model_attribute(self.filtered(lambda r: r.state == 'draft'), '_ensure_boq_request')()
        return super().action_start()

    def action_view_boq_request(self):
        """View boq request."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'construction.equipment.request',
            'view_mode': 'form',
            'res_id': self.request_id.id,
        }
