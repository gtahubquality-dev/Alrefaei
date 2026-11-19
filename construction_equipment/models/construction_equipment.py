"""Construction equipment construction equipment support."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from .runtime import call_method


class ConstructionEquipment(models.Model):
    """Construction Equipment."""

    _inherit = 'construction.equipment'
    track_in_inventory = fields.Boolean(
        string='Track in Inventory',
        default=True,
        help=(
            'The equipment is registered as a stock item and '
            'moves between the main yard and project warehouses '
            'through inventory transfers.'
        ),
    )
    product_id = fields.Many2one(
        'product.product', string='Inventory Item', readonly=True, copy=False
    )
    stock_location_id = fields.Many2one(
        'stock.location', string='Stock Location', compute='_compute_stock_location'
    )
    movement_count = fields.Integer(compute='_compute_totals', string='Movements Count')
    movement_ids = fields.One2many(
        'construction.equipment.movement', 'equipment_id', string='Movements'
    )
    usage_ids = fields.One2many('construction.equipment.usage', 'equipment_id', string='Usage Logs')
    expense_ids = fields.One2many(
        'construction.equipment.expense', 'equipment_id', string='Expenses'
    )
    total_hours = fields.Float(compute='_compute_totals', string='Total Hours')
    total_usage_cost = fields.Monetary(compute='_compute_totals', string='Allocated Usage Cost')
    total_maintenance_cost = fields.Monetary(
        compute='_compute_totals', string='Maintenance & Repair'
    )
    total_rental_cost = fields.Monetary(compute='_compute_totals', string='Rental Cost')
    total_other_cost = fields.Monetary(compute='_compute_totals', string='Fuel, Transport & Other')

    def _get_project_at(self, when):
        """Project where the equipment was located at the given datetime (False = main yard),
        rebuilt from the history of completed movements (supports retroactive entries)."""
        self.ensure_one()
        when = fields.Datetime.to_datetime(when)
        if not when:
            return self.current_project_id
        movement_model = self.env['construction.equipment.movement'].sudo()
        before = movement_model.search(
            [('equipment_id', '=', self.id), ('state', '=', 'done'), ('move_datetime', '<=', when)],
            order='move_datetime desc, id desc',
            limit=1,
        )
        if before:
            return before.to_project_id
        after = movement_model.search(
            [('equipment_id', '=', self.id), ('state', '=', 'done'), ('move_datetime', '>', when)],
            order='move_datetime asc, id asc',
            limit=1,
        )
        if after:
            return after.from_project_id
        return self.current_project_id

    def _compute_stock_location(self):
        quant_model = self.env['stock.quant'].sudo()
        for equipment in self:
            location = False
            if equipment.product_id:
                quant = quant_model.search(
                    [
                        ('product_id', '=', equipment.product_id.id),
                        ('location_id.usage', '=', 'internal'),
                        ('quantity', '>', 0),
                    ],
                    limit=1,
                )
                location = quant.location_id
            equipment.stock_location_id = location

    def _compute_totals(self):
        for equipment in self:
            equipment.movement_count = len(equipment.movement_ids)
            usages = equipment.usage_ids.filtered(lambda u: u.state == 'posted')
            expenses = equipment.expense_ids.filtered(lambda e: e.state in ('submitted', 'billed'))
            equipment.total_hours = sum(usages.mapped('hours'))
            equipment.total_usage_cost = sum(usages.mapped('total_cost'))
            equipment.total_maintenance_cost = sum(
                expenses.filtered(lambda e: e.expense_type in ('maintenance', 'repair')).mapped(
                    'amount'
                )
            )
            equipment.total_rental_cost = sum(
                expenses.filtered(lambda e: e.expense_type == 'rental').mapped('amount')
            )
            equipment.total_other_cost = sum(
                expenses.filtered(
                    lambda e: e.expense_type not in ('maintenance', 'repair', 'rental')
                ).mapped('amount')
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Create records using the existing equipment defaults and sequencing."""
        for vals in vals_list:
            if vals.get('ownership') == 'rented' and 'track_in_inventory' not in vals:
                vals['track_in_inventory'] = False
        equipment = super().create(vals_list)
        call_method(equipment.filtered('track_in_inventory'), '_create_inventory_item')
        return equipment

    def write(self, vals):
        """Update records while preserving the equipment workflow checks."""
        res = super().write(vals)
        if vals.get('track_in_inventory'):
            call_method(
                self.filtered(lambda e: e.track_in_inventory and (not e.product_id)),
                '_create_inventory_item',
            )
        return res

    def _get_yard_warehouse(self):
        self.ensure_one()
        warehouse = self.company_id.construction_equipment_warehouse_id
        if not warehouse:
            project_warehouses = (
                self.env['construction.project']
                .sudo()
                .search([('company_id', '=', self.company_id.id)])
                .warehouse_id
            )
            warehouse = (
                self.env['stock.warehouse']
                .sudo()
                .search(
                    [
                        ('company_id', '=', self.company_id.id),
                        ('id', 'not in', project_warehouses.ids),
                    ],
                    limit=1,
                )
            )
        if not warehouse:
            raise UserError(
                _(
                    (
                        'Please configure the equipment main yard warehouse '
                        'in Construction settings.'
                    )
                )
            )
        return warehouse

    def _create_inventory_item(self):
        product_model = self.env['product.product'].sudo()
        quant_model = self.env['stock.quant'].sudo()
        for equipment in self.filtered(lambda e: not e.product_id):
            product = product_model.with_company(equipment.company_id).create(
                {
                    'name': equipment.name,
                    'default_code': equipment.code,
                    'type': 'consu',
                    'is_storable': True,
                    'sale_ok': False,
                    'purchase_ok': False,
                    'standard_price': equipment.purchase_value,
                    'company_id': equipment.company_id.id,
                }
            )
            equipment.product_id = product
            if equipment.current_project_id:
                location = equipment.current_project_id.warehouse_id.lot_stock_id
            else:
                location = call_method(equipment, '_get_yard_warehouse').lot_stock_id
            call_method(quant_model, '_update_available_quantity', product, location, 1.0)

    def _check_no_open_movement(self, exclude=None):
        for equipment in self:
            open_moves = equipment.sudo().movement_ids.filtered(
                lambda m: m.state in ('draft', 'in_transit')
            )
            if exclude:
                open_moves -= exclude
            if open_moves:
                raise UserError(
                    _(
                        (
                            'Equipment %(equipment)s already has an open '
                            'movement (%(moves)s). Confirm or cancel it first.'
                        ),
                        equipment=equipment.display_name,
                        moves=', '.join(open_moves.mapped('name')),
                    )
                )

    def _check_can_move(self):
        res = super()._check_can_move()
        self._check_no_open_movement()
        return res

    def _check_can_change_state(self):
        res = super()._check_can_change_state()
        for equipment in self:
            if equipment.sudo().movement_ids.filtered(lambda m: m.state == 'in_transit'):
                raise UserError(
                    _(
                        'Equipment %s is in transit. Confirm its arrival first.',
                        equipment.display_name,
                    )
                )
        return res
