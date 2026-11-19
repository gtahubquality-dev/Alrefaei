"""Construction fleet construction driver support."""

from odoo import api, fields, models


class ConstructionDriver(models.Model):
    """Construction Driver."""

    _name = 'construction.driver'
    _description = 'Driver'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    name = fields.Char(string='Full Name', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company
    )
    employee_id = fields.Many2one(
        'hr.employee.public',
        string='Employee',
        index=True,
        tracking=True,
        help='Employee record used for the driver custody.',
    )
    license_number = fields.Char(string='Driving License Number', required=True, tracking=True)
    license_type = fields.Char(string='License Class')
    license_expiry = fields.Date(string='License Expiry', tracking=True)
    id_number = fields.Char(string='National ID / Iqama Number', required=True, tracking=True)
    mobile = fields.Char(string='Mobile Number', required=True)
    employment_status = fields.Selection(
        [
            ('active', 'Active'),
            ('on_leave', 'On Leave'),
            ('suspended', 'Suspended'),
            ('external', 'External / Contracted'),
            ('terminated', 'Terminated'),
        ],
        string='Employment Status',
        required=True,
        default='active',
        tracking=True,
    )
    vehicle_ids = fields.One2many('construction.equipment', 'driver_id', string='Assigned Vehicles')
    document_ids = fields.One2many('construction.driver.document', 'driver_id', string='Documents')
    document_count = fields.Integer(compute='_compute_document_count', string='Documents Count')
    license_expired = fields.Boolean(compute='_compute_license_expired', string='License Expired')
    note = fields.Text(string='Notes')
    _license_company_uniq = models.Constraint(
        'unique(license_number, company_id)', 'This driving license number is already registered.'
    )

    def _compute_document_count(self):
        for driver in self:
            driver.document_count = len(driver.document_ids)

    @api.depends('license_expiry')
    def _compute_license_expired(self):
        today = fields.Date.context_today(self)
        for driver in self:
            driver.license_expired = bool(driver.license_expiry and driver.license_expiry < today)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for driver in self:
            if driver.employee_id:
                driver.name = driver.employee_id.name
                driver.mobile = (
                    driver.mobile
                    or driver.employee_id.mobile_phone
                    or driver.employee_id.work_phone
                )

    @api.depends('name', 'license_number')
    def _compute_display_name(self):
        for driver in self:
            driver.display_name = driver.name or ''
