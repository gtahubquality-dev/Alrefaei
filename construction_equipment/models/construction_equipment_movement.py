"""Construction equipment construction equipment movement support."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from .runtime import call_method
from .equipment_fields import reference_field, tracked_equipment_field, status_field


class ConstructionEquipmentMovement(models.Model):
    """Construction Equipment Movement."""

    _name = 'construction.equipment.movement'
    _description = 'Equipment Movement'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    name = reference_field()
    equipment_id = tracked_equipment_field()
    company_id = fields.Many2one(related='equipment_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='equipment_id.currency_id', string='Currency')
    from_project_id = fields.Many2one(
        'construction.project',
        string='From Project',
        tracking=True,
        help='Leave empty when the equipment comes from the main yard.',
    )
    to_project_id = fields.Many2one(
        'construction.project',
        string='To Project',
        tracking=True,
        help='Leave empty to return the equipment to the main yard.',
    )
    date = fields.Date(string='Movement Date', compute='_compute_date', store=True)
    move_datetime = fields.Datetime(
        string='Movement Date & Time',
        required=True,
        default=fields.Datetime.now,
        help=(
            'Time the equipment arrived at its destination. '
            'Expenses are charged to the project where the '
            'equipment was at the time of the expense.'
        ),
    )
    driver_id = fields.Many2one('hr.employee', string='Driver / Transporter')
    transport_vendor_id = fields.Many2one('res.partner', string='Transport Vendor')
    transport_cost = fields.Monetary(string='Transport Cost')
    request_id = fields.Many2one(
        'construction.equipment.request', string='Equipment Request', readonly=True
    )
    expense_id = fields.Many2one(
        'construction.equipment.expense', string='Transport Expense', readonly=True, copy=False
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Inventory Transfer', readonly=True, copy=False
    )
    state = status_field(
        [
            ('draft', 'Draft'),
            ('in_transit', 'In Transit'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ]
    )
    note = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        """Create records using the existing equipment defaults and sequencing."""
        equipment_model = self.env['construction.equipment']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.equipment.movement'
                ) or _('New')
            if 'from_project_id' not in vals and vals.get('equipment_id'):
                vals['from_project_id'] = equipment_model.browse(
                    vals['equipment_id']
                ).current_project_id.id
        return super().create(vals_list)

    @api.depends('move_datetime')
    def _compute_date(self):
        for movement in self:
            movement.date = (
                fields.Datetime.context_timestamp(movement, movement.move_datetime).date()
                if movement.move_datetime
                else False
            )

    @api.onchange('equipment_id')
    def _onchange_equipment_id(self):
        for movement in self:
            movement.from_project_id = movement.equipment_id.current_project_id

    @api.constrains('from_project_id', 'to_project_id', 'transport_cost')
    def _check_projects(self):
        for movement in self:
            if movement.from_project_id == movement.to_project_id:
                raise ValidationError(
                    _(
                        (
                            'Source and destination must be different (a project '
                            'site or the main yard).'
                        )
                    )
                )
            if movement.transport_cost < 0:
                raise ValidationError(_('Transport cost cannot be negative.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_equipment_movement(self):
        for movement in self:
            if movement.state == 'done':
                raise UserError(_('Completed movements cannot be deleted.'))

    def _check_transport_rights(self):
        if not (
            self.env.user.has_group('construction_management.group_construction_transport')
            or self.env.user.has_group('construction_management.group_construction_manager')
        ):
            raise UserError(_(('Only the Equipment Transportation Manager can confirm movements.')))

    def _get_stock_location(self, project):
        """Stock location of a project site, or of the main yard when no project is given."""
        self.ensure_one()
        if project:
            if not project.warehouse_id:
                raise UserError(_('Project %s has no warehouse.', project.display_name))
            return project.warehouse_id
        return call_method(self.equipment_id, '_get_yard_warehouse')

    def action_done(self):
        """Confirm the movement. Equipment tracked in inventory moves through an internal
        transfer between the source and destination warehouses; the movement completes
        when the transfer is done."""
        self._check_transport_rights()
        for movement in self:
            if movement.state != 'draft':
                raise UserError(_('Only draft movements can be confirmed.'))
            equipment = movement.equipment_id
            if equipment.current_project_id != movement.from_project_id:
                raise UserError(
                    _(
                        (
                            'Equipment %(equipment)s is currently at '
                            '%(location)s, not at the movement source.'
                        ),
                        equipment=equipment.display_name,
                        location=equipment.current_project_id.display_name or _('the main yard'),
                    )
                )
            if equipment.state in ('maintenance', 'inactive'):
                raise UserError(
                    _('Equipment %s is not available for movement.', equipment.display_name)
                )
            if equipment.sudo().movement_ids.filtered(
                lambda m, movement=movement: m.state == 'in_transit' and m != movement
            ):
                raise UserError(
                    _(
                        'Equipment %s is already in transit. Confirm its arrival first.',
                        equipment.display_name,
                    )
                )
            if self.env.su and self.env.context.get('construction_skip_inventory'):
                call_method(movement, '_finalize')
                continue
            if equipment.track_in_inventory and (not equipment.product_id):
                call_method(equipment.sudo(), '_create_inventory_item')
            if equipment.product_id:
                call_method(movement, '_create_transfer')
                movement.state = 'in_transit'
            else:
                call_method(movement, '_finalize')
        return True

    def _create_transfer(self):
        self.ensure_one()
        source_wh = self._get_stock_location(self.from_project_id)
        dest_wh = self._get_stock_location(self.to_project_id)
        if not source_wh.int_type_id:
            raise UserError(
                _('Warehouse %s has no internal transfer operation type.', source_wh.name)
            )
        product = self.equipment_id.product_id
        picking = (
            self.env['stock.picking']
            .sudo()
            .with_company(self.company_id)
            .create(
                {
                    'picking_type_id': source_wh.int_type_id.id,
                    'location_id': source_wh.lot_stock_id.id,
                    'location_dest_id': dest_wh.lot_stock_id.id,
                    'origin': self.name,
                    'construction_project_id': self.to_project_id.id or self.from_project_id.id,
                    'construction_equipment_movement_id': self.id,
                    'company_id': self.company_id.id,
                    'move_ids': [
                        Command.create(
                            {
                                'product_id': product.id,
                                'product_uom_qty': 1.0,
                                'product_uom': product.uom_id.id,
                                'location_id': source_wh.lot_stock_id.id,
                                'location_dest_id': dest_wh.lot_stock_id.id,
                                'company_id': self.company_id.id,
                            }
                        )
                    ],
                }
            )
        )
        picking.action_confirm()
        picking.action_assign()
        self.picking_id = picking

    def action_confirm_arrival(self):
        """Validate the inventory transfer when the equipment arrives on site."""
        self._check_transport_rights()
        for movement in self:
            if movement.state != 'in_transit' or not movement.picking_id:
                raise UserError(_('Only movements in transit can be confirmed as arrived.'))
            picking = movement.picking_id.sudo()
            if picking.state != 'done':
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                call_method(picking, '_action_done')
            if movement.state != 'done':
                call_method(movement, '_finalize')
        return True

    def _finalize(self):
        expense_model = self.env['construction.equipment.expense'].sudo()
        now = fields.Datetime.now()
        for movement in self.filtered(lambda m: m.state in ('draft', 'in_transit')):
            if (
                movement.create_date
                and movement.move_datetime
                and (abs((movement.move_datetime - movement.create_date).total_seconds()) < 120)
            ):
                movement.sudo().move_datetime = now
            equipment = movement.equipment_id.sudo()
            equipment.write(
                {
                    'current_project_id': movement.to_project_id.id,
                    'state': 'in_use' if movement.to_project_id else 'available',
                    'location_note': (
                        movement.to_project_id.display_name
                        if movement.to_project_id
                        else _('Main Yard')
                    ),
                }
            )
            vals = {'state': 'done'}
            if movement.transport_cost > 0:
                expense = expense_model.create(
                    {
                        'equipment_id': equipment.id,
                        'project_id': (movement.to_project_id or movement.from_project_id).id,
                        'expense_type': 'transport',
                        'vendor_id': movement.transport_vendor_id.id,
                        'expense_datetime': movement.move_datetime,
                        'amount': movement.transport_cost,
                        'description': _('Transport %s', movement.name),
                    }
                )
                vals['expense_id'] = expense.id
            movement.sudo().write(vals)
        return True

    def _cancel_from_transfer(self):
        """The inventory transfer of the movement was cancelled from Inventory."""
        for movement in self.filtered(lambda m: m.state == 'in_transit'):
            movement.write({'state': 'cancelled'})
            movement.message_post(
                body=_(('The inventory transfer was cancelled: the movement is cancelled.'))
            )
            request = movement.request_id
            if request.state == 'assigned' and request.movement_id == movement:
                request.write(
                    {'state': 'submitted', 'movement_id': False, 'source_project_id': False}
                )
                request.message_post(
                    body=_(
                        (
                            'Movement %s was cancelled: the request is waiting '
                            'for equipment again.'
                        ),
                        movement.name,
                    )
                )

    def action_view_picking(self):
        """Action view picking."""
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_('No inventory transfer is linked to this movement.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
        }

    def action_cancel(self):
        """Action cancel."""
        for movement in self:
            if movement.state == 'done':
                raise UserError(
                    _(
                        (
                            'Completed movements cannot be cancelled. Create a '
                            'return movement instead.'
                        )
                    )
                )
            if movement.picking_id and movement.picking_id.sudo().state not in ('done', 'cancel'):
                movement.picking_id.sudo().action_cancel()
        self.write({'state': 'cancelled'})
        return True
