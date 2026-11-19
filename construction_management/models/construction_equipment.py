"""Construction equipment for construction management."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .construction_common import analytic_lines_action, company_field
from .runtime import model_attribute

EQUIPMENT_CATEGORIES = [
    ('truck_heavy', 'Truck - Heavy Transport'),
    ('truck_light', 'Truck - Light Transport'),
    ('trailer', 'Trailer'),
    ('sweeper', 'Sweeper'),
    ('tractor', 'Tractor'),
    ('equipment', 'Equipment / Machinery'),
    ('dump_truck', 'Dump Truck'),
    ('private_car', 'Private Car'),
    ('mixer', 'Mixer'),
    ('generator', 'Generator'),
]
VEHICLE_CATEGORIES = (
    'truck_heavy',
    'truck_light',
    'trailer',
    'sweeper',
    'tractor',
    'dump_truck',
    'private_car',
)


class ConstructionEquipment(models.Model):
    """Construction equipment."""

    _name = 'construction.equipment'
    _description = 'Construction Equipment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Equipment Name', required=True, tracking=True)
    code = fields.Char(string='Equipment Code', copy=False, tracking=True)
    active = fields.Boolean(default=True)
    company_id = company_field()
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    category = fields.Selection(
        EQUIPMENT_CATEGORIES,
        string='Machine / Equipment Type',
        required=True,
        default='equipment',
        tracking=True,
    )
    is_vehicle = fields.Boolean(
        string='Is a Vehicle',
        compute='_compute_is_vehicle',
        store=True,
        help=(
            "Vehicles (trucks, trailers, sweepers, tractors, dump trucks, private cars) have a "
            "plate number and an assigned driver and are managed through the driver custody. "
            "Machines (equipment, mixers, generators) are costed by operating hours."
        ),
    )
    equipment_type = fields.Char(string='Model')
    serial_number = fields.Char(string='Serial Number')
    license_plate = fields.Char(string='Plate Number', tracking=True)
    vin_number = fields.Char(string='Chassis Number (VIN)', tracking=True)
    color = fields.Char(string='Color')
    model_year = fields.Char(string='Model Year')
    acquisition_date = fields.Date(string='Purchase / Rental Start Date', tracking=True)
    rental_end_date = fields.Date(string='Rental End Date')
    ownership = fields.Selection(
        [
            ('owned', 'Company Owned'),
            ('rented', 'Rented'),
        ],
        string='Ownership',
        required=True,
        default='owned',
        tracking=True,
    )
    rental_vendor_id = fields.Many2one('res.partner', string='Rental Vendor')
    purchase_value = fields.Monetary(string='Purchase Value')
    depreciation_amount = fields.Monetary(string='Monthly Depreciation', tracking=True)
    depreciation_per_hour = fields.Monetary(string='Depreciation per Hour', tracking=True)
    operating_cost_per_hour = fields.Monetary(string='Operating Cost per Hour', tracking=True)
    diesel_per_hour = fields.Float(
        string='Diesel Consumption per Hour (L)', digits=(16, 3), tracking=True
    )
    diesel_price = fields.Monetary(string='Diesel Price per Liter')
    hourly_rate = fields.Monetary(
        compute='_compute_hourly_rate',
        store=True,
        string='Total Hourly Cost',
        help="Operating cost + depreciation + diesel cost per hour.",
    )
    state = fields.Selection(
        [
            ('available', 'Available'),
            ('in_use', 'On Project Site'),
            ('maintenance', 'Under Maintenance'),
            ('inactive', 'Out of Service'),
        ],
        string='Status',
        default='available',
        required=True,
        tracking=True,
    )
    current_project_id = fields.Many2one(
        'construction.project', string='Current Project', readonly=True, tracking=True, index=True
    )
    location_note = fields.Char(string='Current Location')
    responsible_id = fields.Many2one('hr.employee', string='Operator / Driver')
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Equipment Cost Center', readonly=True, copy=False
    )

    @api.depends('category')
    def _compute_is_vehicle(self):
        for equipment in self:
            equipment.is_vehicle = equipment.category in VEHICLE_CATEGORIES

    @api.constrains('category', 'license_plate', 'active')
    def _check_vehicle_data(self):
        for equipment in self.filtered(lambda e: e.is_vehicle and e.active):
            if not equipment.license_plate:
                raise ValidationError(_('Vehicle %s requires a plate number.', equipment.name))

    def _set_location(self, project):
        """Place the equipment on a project site (or in the main yard when no project is given)."""
        for equipment in self.sudo():
            equipment.write(
                {
                    'current_project_id': project.id if project else False,
                    'state': 'in_use' if project else 'available',
                    'location_note': project.display_name if project else _('Main Yard'),
                }
            )

    def _check_can_move(self):
        """Hook: raise when the equipment cannot be assigned / moved now (extended by Construction
        Equipment)."""
        return True

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)', 'The equipment code must be unique per company.'
    )

    @api.depends(
        'operating_cost_per_hour', 'depreciation_per_hour', 'diesel_per_hour', 'diesel_price'
    )
    def _compute_hourly_rate(self):
        for equipment in self:
            equipment.hourly_rate = (
                equipment.operating_cost_per_hour
                + equipment.depreciation_per_hour
                + equipment.diesel_per_hour * equipment.diesel_price
            )

    @api.constrains(
        'depreciation_amount',
        'depreciation_per_hour',
        'operating_cost_per_hour',
        'diesel_per_hour',
        'diesel_price',
        'purchase_value',
    )
    def _check_values(self):
        for equipment in self:
            values = (
                equipment.depreciation_amount,
                equipment.depreciation_per_hour,
                equipment.operating_cost_per_hour,
                equipment.diesel_per_hour,
                equipment.diesel_price,
                equipment.purchase_value,
            )
            if any(value < 0 for value in values):
                raise ValidationError(_('Equipment costs and consumption cannot be negative.'))

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        equipment = super().create(vals_list)
        model_attribute(equipment, '_create_analytic_account')()
        return equipment

    def _create_analytic_account(self):
        plan = self.env.ref(
            'construction_management.analytic_plan_construction_equipment', raise_if_not_found=False
        )
        if not plan:
            plan = (
                self.env['account.analytic.plan']
                .sudo()
                .create({'name': _('Construction Equipment')})
            )
        for equipment in self.filtered(lambda e: not e.analytic_account_id):
            equipment.analytic_account_id = (
                self.env['account.analytic.account']
                .sudo()
                .create(
                    {
                        'name': equipment.name,
                        'code': equipment.code,
                        'plan_id': plan.id,
                        'company_id': equipment.company_id.id,
                    }
                )
            )

    def _get_analytic_distribution(self, project=None):
        self.ensure_one()
        distribution = {}
        if project and project.analytic_account_id:
            distribution[str(project.analytic_account_id.id)] = 100.0
        if self.analytic_account_id:
            distribution[str(self.analytic_account_id.id)] = 100.0
        return distribution or False

    @api.depends('name', 'code', 'license_plate')
    def _compute_display_name(self):
        for equipment in self:
            name = (
                f'[{equipment.code}] {equipment.name}' if equipment.code else (equipment.name or '')
            )
            if equipment.license_plate:
                name = f'{name} ({equipment.license_plate})'
            equipment.display_name = name

    def _check_can_change_state(self):
        """Hook: raise when the equipment status cannot be changed now (extended by Construction
        Equipment)."""
        return True

    def action_set_maintenance(self):
        """Set maintenance."""
        self._check_can_change_state()
        self.write({'state': 'maintenance'})

    def action_set_available(self):
        """Set available."""
        for equipment in self:
            equipment.state = 'in_use' if equipment.current_project_id else 'available'

    def action_set_inactive(self):
        """Set inactive."""
        self._check_can_change_state()
        self.write({'state': 'inactive'})

    def action_view_analytic_lines(self):
        """View analytic lines."""
        self.ensure_one()
        if not self.analytic_account_id:
            raise UserError(_('No cost center is linked to this equipment.'))
        return analytic_lines_action(self.analytic_account_id, _('Equipment Cost Center Items'))
