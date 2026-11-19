"""Construction equipment request construction equipment for construction management."""

from odoo import Command
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .runtime import model_attribute

from .construction_common import (
    reset_cancelled_requests,
    project_field,
    reference_field,
    requester_field,
    workflow_status_field,
)


class ConstructionEquipmentRequest(models.Model):
    """Construction equipment request."""

    _name = 'construction.equipment.request'
    _description = 'Equipment Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    name = reference_field()
    project_id = project_field()
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    description = fields.Char(string='Required Equipment', required=True)
    date_from = fields.Date(string='From', required=True, default=fields.Date.context_today)
    date_to = fields.Date(string='To')
    expected_hours = fields.Float(string='Expected Operating Hours')
    requested_by_id = requester_field()
    boq_component_id = fields.Many2one(
        'construction.boq.component',
        string='BOQ Equipment',
        tracking=True,
        index=True,
        domain="[('project_id', '=', project_id), ('component_type', '=', 'equipment')]",
        help=(
            "Equipment component of the BOQ item this request is charged to. Requests beyond the"
            " BOQ quantity (or without BOQ equipment) require the approval of Senior Management."
        ),
    )
    boq_item_id = fields.Many2one(related='boq_component_id.item_id', store=True, string='BOQ Item')
    requested_quantity = fields.Float(
        string='Requested Quantity',
        digits='Product Unit',
        default=1.0,
        tracking=True,
        help="Requested duration, in the unit of the BOQ equipment (days, hours...).",
    )
    boq_uom_id = fields.Many2one(related='boq_component_id.uom_id', string='Unit')
    boq_quantity = fields.Float(
        related='boq_component_id.effective_quantity', string='BOQ Quantity'
    )
    boq_remaining = fields.Float(
        compute='_compute_boq_remaining',
        string='Remaining in BOQ',
        help="BOQ quantity not yet requested by the other requests of this equipment.",
    )
    exceeds_boq = fields.Boolean(string='Exceeds BOQ', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('to_approve', 'Waiting Senior Management'),
            ('submitted', 'Submitted'),
            ('assigned', 'Company Equipment Assigned'),
            ('rental', 'External Rental'),
            ('done', 'Released'),
            ('cancelled', 'Cancelled'),
        ]
    )
    equipment_id = fields.Many2one(
        'construction.equipment',
        string='Assigned Equipment',
        tracking=True,
        domain="[('company_id', '=', company_id), ('state', 'in', ('available', 'in_use'))]",
    )
    source_project_id = fields.Many2one(
        'construction.project',
        string='Equipment Came From',
        readonly=True,
        copy=False,
        help="Location of the assigned equipment before the assignment (empty = main yard).",
    )
    rental_vendor_id = fields.Many2one('res.partner', string='Rental Vendor')
    rental_product_id = fields.Many2one(
        'product.product',
        string='Rental Service',
        domain="[('type', '=', 'service'), ('purchase_ok', '=', True)]",
    )
    rental_quantity = fields.Float(string='Rental Quantity', default=1.0)
    rental_price = fields.Monetary(string='Rental Unit Price')
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Rental Purchase Order', readonly=True, copy=False
    )
    rental_order_ids = fields.One2many(
        'purchase.order', 'construction_equipment_request_id', string='Rental Purchase Orders'
    )
    rented_equipment_id = fields.Many2one(
        'construction.equipment',
        string='Rented Equipment',
        domain="[('ownership', '=', 'rented'), ('company_id', '=', company_id)]",
        help=(
            "Optional: the rented equipment registered in the equipment register, to follow its"
            " location, usage and expenses on the project."
        ),
    )
    rental_extension_qty = fields.Float(
        string='Extension Quantity',
        help=(
            "Additional rental quantity (days, months...) to order, in the unit of the requested"
            " quantity."
        ),
    )
    note = fields.Text(string='Notes')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for request in self:
            if request.date_to and request.date_from and request.date_to < request.date_from:
                raise ValidationError(_('The end date cannot be before the start date.'))

    @api.constrains('boq_component_id', 'project_id', 'requested_quantity')
    def _check_boq_component(self):
        for request in self:
            component = request.boq_component_id
            if component and (
                component.project_id != request.project_id
                or component.component_type != 'equipment'
            ):
                raise ValidationError(
                    _(
                        'Please select an equipment component of the BOQ of project %s.',
                        request.project_id.display_name,
                    )
                )
            if request.requested_quantity < 0:
                raise ValidationError(_('The requested quantity cannot be negative.'))

    def _get_boq_consumption(self):
        """Quantity of the BOQ equipment already requested by the other active requests."""
        self.ensure_one()
        if not self.boq_component_id:
            return 0.0
        others = self.sudo().search(
            [
                ('boq_component_id', '=', self.boq_component_id.id),
                ('state', 'in', ('to_approve', 'submitted', 'assigned', 'rental', 'done')),
                ('id', 'not in', self.ids),
            ]
        )
        return sum(others.mapped('requested_quantity'))

    @api.depends(
        'boq_component_id', 'boq_component_id.effective_quantity', 'requested_quantity', 'state'
    )
    def _compute_boq_remaining(self):
        for request in self:
            if request.boq_component_id:
                request.boq_remaining = (
                    request.boq_component_id.effective_quantity
                    - model_attribute(request, '_get_boq_consumption')()
                )
            else:
                request.boq_remaining = 0.0

    def _exceeds_boq(self, extra=0.0):
        """True when the request is not covered by the BOQ: no BOQ equipment, or the requested
        quantity (plus ``extra``) exceeds what the other requests left of the BOQ quantity.
        """
        self.ensure_one()
        if not self.boq_component_id:
            return True
        available = self.boq_component_id.effective_quantity - self._get_boq_consumption()
        return float_compare(self.requested_quantity + extra, available, precision_digits=4) > 0

    def _is_senior_manager(self):
        return self.env.user.has_group('construction_management.group_construction_manager')

    def _ensure_within_boq(self):
        """Before processing: a request that was not approved by Senior Management and no longer
        fits in the BOQ (consumed by other requests since its submission) goes back to approval.
        Returns False then.
        """
        self.ensure_one()
        if self.approved_by_id or not self._exceeds_boq():
            return True
        self.write({'state': 'to_approve', 'exceeds_boq': True})
        self.message_post(
            body=_(
                'The BOQ equipment quantity was consumed by other requests since submission: the '
                'request now requires the approval of Senior Management.'
            )
        )
        return False

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.equipment.request'
                ) or _('New')
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_equipment_request(self):
        for request in self:
            if request.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled equipment requests can be deleted.'))

    def _check_transport_manager(self):
        if not (
            self.env.user.has_group('construction_management.group_construction_transport')
            or self.env.user.has_group('construction_management.group_construction_manager')
        ):
            raise UserError(
                _('Only the Equipment Transportation Manager can process equipment requests.')
            )

    def action_submit(self):
        """Submit."""
        for request in self:
            if request.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if float_compare(request.requested_quantity, 0.0, precision_digits=4) <= 0:
                raise UserError(_('Please enter the requested quantity.'))
            exceeds = model_attribute(request, '_exceeds_boq')()
            request.write(
                {
                    'state': 'to_approve' if exceeds else 'submitted',
                    'exceeds_boq': exceeds,
                    'approved_by_id': False,
                    'approved_date': False,
                }
            )
            if exceeds:
                if request.boq_component_id:
                    message = _(
                        'The requested quantity (%(qty)s) exceeds the remaining BOQ quantity of'
                        ' %(item)s (%(remaining)s). Senior Management approval is required.',
                        qty=request.requested_quantity,
                        item=request.boq_component_id.display_name,
                        remaining=request.boq_component_id.effective_quantity
                        - model_attribute(request, '_get_boq_consumption')(),
                    )
                else:
                    message = _(
                        'The request is not linked to an equipment of the BOQ. Senior Management'
                        ' approval is required.'
                    )
                request.message_post(body=message)
        return True

    def action_approve(self):
        """Approve."""
        if not self._is_senior_manager():
            raise UserError(
                _('Only Senior Management can approve equipment requests exceeding the BOQ.')
            )
        for request in self:
            if request.state != 'to_approve':
                raise UserError(_('Only requests waiting for Senior Management can be approved.'))
        self.write(
            {
                'state': 'submitted',
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            }
        )
        return True

    def action_reject(self):
        """Reject."""
        if not self._is_senior_manager():
            raise UserError(_('Only Senior Management can reject equipment requests.'))
        for request in self:
            if request.state != 'to_approve':
                raise UserError(_('Only requests waiting for Senior Management can be rejected.'))
            request.message_post(body=_('Request rejected by %s.', self.env.user.name))
        self.write({'state': 'cancelled'})
        return True

    def action_assign(self):
        """Assign."""
        self._check_transport_manager()
        for request in self:
            if request.state != 'submitted':
                raise UserError(_('Only submitted requests can be assigned.'))
            if not model_attribute(request, '_ensure_within_boq')():
                continue
            if not request.equipment_id:
                raise UserError(_('Please select the company equipment to assign.'))
            if request.equipment_id.state not in ('available', 'in_use'):
                raise UserError(
                    _('Equipment %s is not available.', request.equipment_id.display_name)
                )
            model_attribute(request.equipment_id, '_check_can_move')()
            if request.equipment_id.current_project_id == request.project_id:
                raise UserError(
                    _(
                        'Equipment %s is already on this project site.',
                        request.equipment_id.display_name,
                    )
                )
            request.write(
                {
                    'state': 'assigned',
                    'source_project_id': request.equipment_id.current_project_id.id,
                }
            )
            model_attribute(request, '_dispatch_equipment')(request.equipment_id)
        return True

    def _dispatch_equipment(self, equipment):
        """Send the assigned company equipment to the project site.
        Placed on site immediately; Construction Equipment replaces this with a movement / inventory
        transfer.
        """
        self.ensure_one()
        model_attribute(equipment, '_set_location')(self.project_id)

    def _place_rented_equipment(self, equipment):
        """Register the rented equipment on the project site."""
        self.ensure_one()
        model_attribute(equipment, '_set_location')(self.project_id)

    def _recall_equipment(self):
        """Undo the dispatch of the assigned equipment (unassign): back to where it came from."""
        self.ensure_one()
        if self.equipment_id.current_project_id == self.project_id:
            model_attribute(self.equipment_id, '_set_location')(self.source_project_id)

    def _check_can_release(self):
        """Hook: raise when the request cannot be released yet."""
        return True

    def _return_equipment(self, equipment):
        """The request is released while the equipment is still on site: send it back to the main
        yard."""
        self.ensure_one()
        model_attribute(equipment, '_set_location')(False)

    def action_request_rental(self):
        """Request rental."""
        self._check_transport_manager()
        for request in self:
            if request.state != 'submitted':
                raise UserError(_('Only submitted requests can be rented externally.'))
            if not model_attribute(request, '_ensure_within_boq')():
                continue
            if not request.rental_vendor_id or not request.rental_product_id:
                raise UserError(_('Please set the rental vendor and the rental service product.'))
            if float_compare(request.rental_quantity, 0.0, precision_digits=4) <= 0:
                raise UserError(_('The rental quantity must be positive.'))
            project = request.project_id
            if not project.warehouse_id:
                raise UserError(_('Project %s has no warehouse.', project.display_name))
            order = (
                self.env['purchase.order']
                .sudo()
                .with_company(request.company_id)
                .create(
                    {
                        'partner_id': request.rental_vendor_id.id,
                        'company_id': request.company_id.id,
                        'picking_type_id': project.warehouse_id.in_type_id.id,
                        'origin': f'{project.code} / {request.name}',
                        'construction_project_id': project.id,
                        'construction_equipment_request_id': request.id,
                        'order_line': [
                            Command.create(
                                {
                                    'product_id': request.rental_product_id.id,
                                    'name': (
                                        f'{request.rental_product_id.display_name} -'
                                        f' {request.description}'
                                    ),
                                    'product_qty': request.rental_quantity,
                                    'price_unit': request.rental_price,
                                    'analytic_distribution': model_attribute(
                                        project, '_get_analytic_distribution'
                                    )(),
                                }
                            )
                        ],
                    }
                )
            )
            request.write({'state': 'rental', 'purchase_order_id': order.id})
            rented = request.rented_equipment_id
            if rented and rented.current_project_id != project:
                model_attribute(rented, '_check_can_move')()
                model_attribute(request, '_place_rented_equipment')(rented)
        return True

    def action_unassign(self):
        """Cancel the assignment of company equipment (wrong equipment, change of plan)."""
        self._check_transport_manager()
        for request in self:
            if request.state != 'assigned':
                raise UserError(_('Only assigned requests can be unassigned.'))
            model_attribute(request, '_recall_equipment')()
            request.write({'state': 'submitted', 'source_project_id': False})
            request.message_post(
                body=_('Assignment cancelled; the request is waiting for equipment again.')
            )
        return True

    def _rental_qty_in_boq_unit(self, quantity):
        """A rental quantity (unit of the rental service: hours, days...) in the unit of the BOQ
        equipment."""
        self.ensure_one()
        rental_uom = self.rental_product_id.uom_id
        boq_uom = self.boq_component_id.uom_id
        if not rental_uom or not boq_uom:
            return quantity
        return model_attribute(rental_uom, '_compute_quantity')(
            quantity, boq_uom, round=False, raise_if_failure=False
        )

    def action_extend_rental(self):
        """Extend an external rental after it started: add the quantity to the rental purchase order
        (or create a new order when the previous one can no longer be modified)."""
        self._check_transport_manager()
        for request in self:
            if request.state != 'rental':
                raise UserError(_('Only running rentals can be extended.'))
            if float_compare(request.rental_extension_qty, 0.0, precision_digits=4) <= 0:
                raise UserError(_('Please enter the extension quantity.'))
            extension_boq_qty = model_attribute(request, '_rental_qty_in_boq_unit')(
                request.rental_extension_qty
            )
            if (
                model_attribute(request, '_exceeds_boq')(extra=extension_boq_qty)
                and not model_attribute(request, '_is_senior_manager')()
            ):
                raise UserError(
                    _(
                        'The extension exceeds the BOQ equipment quantity of the request: only'
                        ' Senior Management can extend it.'
                    )
                )
            order = request.purchase_order_id.sudo()
            line = order.order_line.filtered(
                lambda line, req=request: line.product_id == req.rental_product_id
            )[:1]
            if order and order.state != 'cancel' and not order.locked and line:
                line.product_qty += request.rental_extension_qty
            else:
                project = request.project_id
                order = (
                    self.env['purchase.order']
                    .sudo()
                    .with_company(request.company_id)
                    .create(
                        {
                            'partner_id': request.rental_vendor_id.id,
                            'company_id': request.company_id.id,
                            'picking_type_id': project.warehouse_id.in_type_id.id,
                            'origin': f'{project.code} / {request.name}',
                            'construction_project_id': project.id,
                            'construction_equipment_request_id': request.id,
                            'order_line': [
                                Command.create(
                                    {
                                        'product_id': request.rental_product_id.id,
                                        'name': (
                                            f'{request.rental_product_id.display_name} -'
                                            f' {request.description}'
                                        ),
                                        'product_qty': request.rental_extension_qty,
                                        'price_unit': request.rental_price,
                                        'analytic_distribution': (
                                            model_attribute(project, '_get_analytic_distribution')()
                                        ),
                                    }
                                )
                            ],
                        }
                    )
                )
                request.purchase_order_id = order
            request.message_post(
                body=_(
                    'Rental extended by %(qty)s (purchase order %(order)s).',
                    qty=request.rental_extension_qty,
                    order=order.name,
                )
            )
            request.write(
                {
                    'rental_quantity': request.rental_quantity + request.rental_extension_qty,
                    'requested_quantity': request.requested_quantity + extension_boq_qty,
                    'rental_extension_qty': 0.0,
                }
            )
        return True

    def _reopen_after_rental_cancel(self, order):
        for request in self.filtered(
            lambda r: r.state == 'rental' and r.purchase_order_id == order
        ):
            other_orders = request.rental_order_ids.filtered(
                lambda o: o != order and o.state != 'cancel'
            )
            if other_orders:
                request.purchase_order_id = other_orders[:1]
                continue
            request.write({'state': 'submitted', 'purchase_order_id': False})
            request.message_post(
                body=_(
                    'Rental purchase order %s was cancelled: the request is waiting for '
                    'equipment again.',
                    order.name,
                )
            )

    def action_release(self):
        """Release the request. Equipment still on the project site is sent back to the main
        yard."""
        if not self.env.su:
            self._check_transport_manager()
        for request in self:
            if request.state not in ('assigned', 'rental'):
                raise UserError(_('Only assigned or rented requests can be released.'))
            model_attribute(request, '_check_can_release')()
            equipment = (
                request.equipment_id if request.state == 'assigned' else request.rented_equipment_id
            )
            request.write({'state': 'done', 'date_to': fields.Date.context_today(self)})
            if (
                equipment
                and equipment.current_project_id == request.project_id
                and not (self.env.su and self.env.context.get('construction_rental_return'))
            ):
                model_attribute(request, '_return_equipment')(equipment)
        return True

    def action_cancel(self):
        """Cancel."""
        for request in self:
            if request.state == 'assigned':
                raise UserError(_('Unassign the equipment before cancelling the request.'))
            if request.state == 'rental':
                raise UserError(
                    _('Cancel the rental purchase order or release the request instead.')
                )
            if request.state == 'done':
                raise UserError(_('Released requests cannot be cancelled.'))
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        return reset_cancelled_requests(
            self,
            exceeds_boq=False,
            approved_by_id=False,
            approved_date=False,
        )
