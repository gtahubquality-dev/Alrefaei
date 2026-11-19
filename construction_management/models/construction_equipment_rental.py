"""Construction equipment rental for construction management."""

from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from .runtime import model_attribute

from .construction_common import company_field, reference_field, workflow_status_field

RATE_TYPES = [
    ('hour', 'Per Hour'),
    ('day', 'Per Day'),
    ('week', 'Per Week'),
    ('month', 'Per Month'),
    ('trip', 'Per Trip'),
    ('lump_sum', 'Lump Sum'),
]


class ConstructionEquipmentRental(models.Model):
    """Rental contract of external equipment, machine or vehicle: who it is rented from, for which
    project, period, rate and purchase orders. It is what makes an equipment "rented" as opposed
    to the company owned equipment (linked to a fixed asset).
    """

    _name = 'construction.equipment.rental'
    _description = 'Equipment Rental Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = reference_field()
    company_id = company_field()
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    partner_id = fields.Many2one(
        'res.partner',
        string='Rental Vendor',
        required=True,
        tracking=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    equipment_id = fields.Many2one(
        'construction.equipment',
        string='Rented Equipment',
        tracking=True,
        index=True,
        domain="[('ownership', '=', 'rented'), ('company_id', '=', company_id)]",
        help="Equipment, machine or vehicle received from the vendor (registered as rented).",
    )
    category = fields.Selection(related='equipment_id.category', string='Type')
    is_vehicle = fields.Boolean(related='equipment_id.is_vehicle', string='Vehicle')
    license_plate = fields.Char(related='equipment_id.license_plate', string='Plate Number')
    project_id = fields.Many2one(
        'construction.project',
        string='Project',
        tracking=True,
        index=True,
        domain="[('company_id', '=', company_id)]",
    )
    request_id = fields.Many2one(
        'construction.equipment.request',
        string='Equipment Request',
        readonly=True,
        copy=False,
        index=True,
    )
    date_start = fields.Date(
        string='Start Date', required=True, default=fields.Date.context_today, tracking=True
    )
    date_end = fields.Date(
        string='End Date', tracking=True, help="Leave empty while the end date is unknown."
    )
    return_date = fields.Date(string='Returned On', readonly=True, copy=False)
    rate_type = fields.Selection(
        RATE_TYPES, string='Rate', required=True, default='day', tracking=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Rental Service',
        domain="[('type', '=', 'service'), ('purchase_ok', '=', True)]",
        help="Service product used on the rental purchase orders.",
    )
    quantity = fields.Float(
        string='Quantity',
        digits='Product Unit',
        default=1.0,
        tracking=True,
        help="Number of hours, days, months... ordered (1 for a lump sum).",
    )
    unit_price = fields.Monetary(string='Unit Price', tracking=True)
    amount = fields.Monetary(string='Contract Amount', compute='_compute_amount', store=True)
    operator_included = fields.Boolean(string='Operator / Driver Included')
    fuel_included = fields.Boolean(string='Fuel Included')
    purchase_order_ids = fields.One2many(
        'purchase.order', 'construction_equipment_rental_id', string='Purchase Orders'
    )
    purchase_order_count = fields.Integer(
        compute='_compute_purchase', string='Purchase Order Count'
    )
    ordered_amount = fields.Monetary(compute='_compute_purchase', string='Ordered')
    billed_amount = fields.Monetary(compute='_compute_purchase', string='Billed')
    extension_date = fields.Date(string='New End Date')
    extension_quantity = fields.Float(string='Additional Quantity', digits='Product Unit')
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('returned', 'Returned'),
            ('cancelled', 'Cancelled'),
        ]
    )
    is_expiring = fields.Boolean(
        compute='_compute_is_expiring', string='Ending Soon', search='_search_is_expiring'
    )
    note = fields.Text(string='Terms')

    _quantity_positive = models.Constraint(
        'CHECK(quantity >= 0)', 'The rental quantity cannot be negative.'
    )

    @api.depends('quantity', 'unit_price')
    def _compute_amount(self):
        for rental in self:
            rental.amount = rental.quantity * rental.unit_price

    def _compute_purchase(self):
        for rental in self:
            orders = rental.sudo().purchase_order_ids.filtered(lambda o: o.state != 'cancel')
            rental.purchase_order_count = len(rental.sudo().purchase_order_ids)
            rental.ordered_amount = sum(orders.mapped('amount_untaxed'))
            bills = orders.invoice_ids.filtered(lambda m: m.state == 'posted')

            rental.billed_amount = -sum(bills.mapped('amount_untaxed_signed'))

    def _compute_is_expiring(self):
        limit = fields.Date.context_today(self) + timedelta(days=7)
        for rental in self:
            rental.is_expiring = (
                rental.state == 'running' and bool(rental.date_end) and rental.date_end <= limit
            )

    def _search_is_expiring(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Unsupported search on this field.'))
        limit = fields.Date.context_today(self) + timedelta(days=7)
        domain = [('state', '=', 'running'), ('date_end', '!=', False), ('date_end', '<=', limit)]
        positive = (operator == '=') == value
        return domain if positive else ['!', '&', '&'] + domain

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rental in self:
            if rental.date_end and rental.date_end < rental.date_start:
                raise ValidationError(_('The end date cannot be before the start date.'))

    @api.constrains('equipment_id', 'state', 'date_start', 'date_end')
    def _check_equipment(self):
        for rental in self.filtered('equipment_id'):
            if rental.equipment_id.ownership != 'rented':
                raise ValidationError(
                    _(
                        '%s is company owned: only rented equipment can have a rental contract.',
                        rental.equipment_id.display_name,
                    )
                )
            if rental.state == 'running':
                other = self.search(
                    [
                        ('id', '!=', rental.id),
                        ('equipment_id', '=', rental.equipment_id.id),
                        ('state', '=', 'running'),
                    ],
                    limit=1,
                )
                if other:
                    raise ValidationError(
                        _(
                            '%(equipment)s already has a running rental contract (%(rental)s).',
                            equipment=rental.equipment_id.display_name,
                            rental=other.name,
                        )
                    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.equipment.rental'
                ) or _('New')
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_started(self):
        for rental in self:
            if rental.state != 'draft' or rental.purchase_order_ids:
                raise UserError(
                    _('Only draft rental contracts without purchase orders can be deleted.')
                )

    @api.onchange('equipment_id')
    def _onchange_equipment_id(self):
        for rental in self:
            if rental.equipment_id.rental_vendor_id and not rental.partner_id:
                rental.partner_id = rental.equipment_id.rental_vendor_id

    def _sync_equipment(self):
        """The register shows the vendor and the period of the running contract."""
        for rental in self.filtered(lambda r: r.equipment_id and r.state == 'running'):
            rental.equipment_id.sudo().write(
                {
                    'rental_vendor_id': rental.partner_id.id,
                    'acquisition_date': rental.date_start,
                    'rental_end_date': rental.date_end,
                }
            )

    def _check_transport_manager(self):
        if not self.env.user.has_group(
            'construction_management.group_construction_transport'
        ) and not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(
                _('Only the transportation manager or Senior Management can manage rentals.')
            )

    def _prepare_purchase_order(self, quantity, label=None):
        self.ensure_one()
        project = self.project_id
        line = {
            'product_id': self.product_id.id,
            'name': (
                label
                or f'{self.product_id.display_name} - {self.equipment_id.display_name or self.name}'
            ),
            'product_qty': quantity,
            'price_unit': self.unit_price,
        }
        vals = {
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'origin': f'{project.code} / {self.name}' if project else self.name,
            'construction_equipment_rental_id': self.id,
            'order_line': [Command.create(line)],
        }
        if project:
            vals['construction_project_id'] = project.id
            line['analytic_distribution'] = model_attribute(project, '_get_analytic_distribution')()
            if project.warehouse_id:
                vals['picking_type_id'] = project.warehouse_id.in_type_id.id
        if self.request_id:
            vals['construction_equipment_request_id'] = self.request_id.id
        return vals

    def action_create_purchase_order(self):
        """Create purchase order."""
        self._check_transport_manager()
        for rental in self:
            if rental.state not in ('draft', 'running'):
                raise UserError(
                    _('Purchase orders can only be created for draft or running rentals.')
                )
            if not rental.product_id:
                raise UserError(_('Please set the rental service product.'))
            if float_compare(rental.quantity, 0.0, precision_digits=4) <= 0:
                raise UserError(_('The rental quantity must be positive.'))
            if rental.purchase_order_ids.filtered(lambda o: o.state != 'cancel'):
                raise UserError(
                    _(
                        'Rental %s already has a purchase order: use "Extend" to order more.',
                        rental.name,
                    )
                )
            self.env['purchase.order'].sudo().with_company(rental.company_id).create(
                model_attribute(rental, '_prepare_purchase_order')(rental.quantity)
            )
        return True

    def action_start(self):
        """Start."""
        self._check_transport_manager()
        for rental in self:
            if rental.state != 'draft':
                raise UserError(_('Only draft rentals can be started.'))
            if not rental.equipment_id:
                raise UserError(_('Please register the rented equipment (Rented Equipment field).'))
        self.write({'state': 'running'})
        self._sync_equipment()
        return True

    def action_extend(self):
        """Extend a running rental: new end date and / or additional quantity added to the purchase
        order."""
        self._check_transport_manager()
        for rental in self:
            if rental.state != 'running':
                raise UserError(_('Only running rentals can be extended.'))
            if (
                not rental.extension_date
                and float_compare(rental.extension_quantity, 0.0, precision_digits=4) <= 0
            ):
                raise UserError(_('Please enter the new end date or the additional quantity.'))
            if (
                rental.extension_date
                and rental.date_end
                and rental.extension_date <= rental.date_end
            ):
                raise UserError(_('The new end date must be after the current end date.'))
            if float_compare(rental.extension_quantity, 0.0, precision_digits=4) > 0:
                if rental.request_id and rental.request_id.state == 'rental':

                    rental.request_id.rental_extension_qty = rental.extension_quantity
                    rental.request_id.with_context(
                        construction_rental_extension=True
                    ).action_extend_rental()
                else:
                    model_attribute(rental, '_extend_purchase')(rental.extension_quantity)
                    rental.quantity += rental.extension_quantity
            vals = {'extension_date': False, 'extension_quantity': 0.0}
            if rental.extension_date:
                vals['date_end'] = rental.extension_date
            rental.message_post(
                body=_(
                    'Rental extended: end date %(date)s, additional quantity %(qty)s.',
                    date=rental.extension_date or rental.date_end or '-',
                    qty=rental.extension_quantity,
                )
            )
            rental.write(vals)
        self._sync_equipment()
        return True

    def _extend_purchase(self, quantity):
        self.ensure_one()
        if not self.product_id:
            return
        order = self.purchase_order_ids.filtered(lambda o: o.state != 'cancel').sorted('id')[-1:]
        if order and order.state in ('draft', 'sent'):
            line = order.order_line.filtered(lambda l: l.product_id == self.product_id)[:1]
            if line:
                line.product_qty += quantity
                return
        self.env['purchase.order'].sudo().with_company(self.company_id).create(
            self._prepare_purchase_order(
                quantity,
                _(
                    '%(product)s - extension of %(rental)s',
                    product=self.product_id.display_name,
                    rental=self.name,
                ),
            )
        )

    def action_return(self):
        """The equipment is returned to the vendor: the contract ends and the equipment leaves the
        sites."""
        self._check_transport_manager()
        today = fields.Date.context_today(self)
        for rental in self:
            if rental.state != 'running':
                raise UserError(_('Only running rentals can be returned.'))
            request = rental.request_id
            if request and request.state == 'rental':
                request.sudo().with_context(construction_rental_return=True).action_release()
            rental.write({'state': 'returned', 'return_date': today})
            equipment = rental.equipment_id.sudo()
            if equipment and not self.search_count(
                [('equipment_id', '=', equipment.id), ('state', '=', 'running')]
            ):
                equipment.write(
                    {
                        'rental_end_date': today,
                        'state': 'inactive',
                        'current_project_id': False,
                        'location_note': _('Returned to %s', rental.partner_id.display_name),
                    }
                )
        return True

    def action_cancel(self):
        """Cancel."""
        self._check_transport_manager()
        for rental in self:
            if rental.state == 'returned':
                raise UserError(_('Returned rentals cannot be cancelled.'))
            if rental.billed_amount:
                raise UserError(_('Rental %s is already billed: return it instead.', rental.name))
            orders = rental.sudo().purchase_order_ids.filtered(lambda o: o.state != 'cancel')
            if orders.filtered(lambda o: o.state not in ('draft', 'sent')):
                raise UserError(_('Cancel the confirmed purchase orders of %s first.', rental.name))
            orders.button_cancel()
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        for rental in self:
            if rental.state != 'cancelled':
                raise UserError(_('Only cancelled rentals can be reset to draft.'))
        self.write({'state': 'draft'})
        return True

    def action_view_purchase_orders(self):
        """View purchase orders."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rental Purchase Orders'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('construction_equipment_rental_id', '=', self.id)],
            'context': {'create': False},
        }

    def _cancel_from_purchase(self, order):
        """The rental purchase order was cancelled: a draft / running contract without other order
        is cancelled."""
        for rental in self.filtered(lambda r: r.state in ('draft', 'running')):
            if rental.purchase_order_ids.filtered(lambda o: o != order and o.state != 'cancel'):
                continue
            rental.write({'state': 'cancelled'})
            rental.message_post(
                body=_('Purchase order %s was cancelled: rental cancelled.', order.name)
            )
