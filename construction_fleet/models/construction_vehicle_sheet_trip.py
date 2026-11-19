"""Construction fleet construction vehicle sheet trip support."""

from odoo import api, fields, models
from odoo.addons.construction_equipment.models.runtime import call_method
from .vehicle_sheet_fields import project_field


class ConstructionVehicleSheetTrip(models.Model):
    """Construction Vehicle Sheet Trip."""

    _name = 'construction.vehicle.sheet.trip'
    _inherit = ['construction.vehicle.sheet.line.mixin']
    _description = 'Vehicle Trip'
    _order = 'sheet_id, date, id'
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    transport_type_id = fields.Many2one(
        'construction.transport.type', string='Trip Type', required=True
    )
    project_id = project_field()
    equipment_id = fields.Many2one(
        'construction.equipment',
        string='Transported Equipment',
        domain="[('is_vehicle', '=', False), ('company_id', '=', company_id)]",
        help='Machine or equipment carried on this trip (equipment transport).',
    )
    from_location = fields.Char(string='From')
    to_location = fields.Char(string='To')
    quantity = fields.Float(string='Quantity Transported', digits='Product Unit', default=1.0)
    uom_id = fields.Many2one(related='transport_type_id.uom_id', string='Unit')
    amount = fields.Monetary(string='Trip Value')
    document_ref = fields.Char(string='Delivery Note / Invoice')
    allocated_amount = fields.Monetary(
        compute='_compute_allocation', store=True, string='Distributed Expenses'
    )
    total_cost = fields.Monetary(
        compute='_compute_allocation', store=True, string='Total Trip Cost'
    )
    unit_cost = fields.Monetary(compute='_compute_allocation', store=True, string='Cost per Unit')

    @api.depends('sheet_id.vehicle_id', 'date')
    def _compute_project_id(self):
        for trip in self:
            vehicle = trip.sheet_id.vehicle_id
            if vehicle and trip.date and (not trip.project_id):
                when = fields.Datetime.to_datetime(trip.date).replace(hour=12)
                trip.project_id = call_method(vehicle, '_get_project_at', when)
            elif not trip.project_id:
                trip.project_id = False

    @api.depends(
        'quantity',
        'amount',
        'sheet_id.expense_ids.amount',
        'sheet_id.expense_ids.distribute',
        'sheet_id.trip_ids.quantity',
        'sheet_id.trip_ids.amount',
        'sheet_id.allocation_method',
    )
    def _compute_allocation(self):
        """Distribute the other expenses (freight, tips...) on the trips in proportion to
        the transported quantity of each trip divided by the total transported quantity
        (or by value, as chosen on the sheet; by value when there is no quantity)."""
        for sheet in self.sheet_id:
            trips = sheet.trip_ids
            other = sum(sheet.expense_ids.filtered('distribute').mapped('amount'))
            total_qty = (
                sum(trips.mapped('quantity')) if sheet.allocation_method == 'quantity' else 0.0
            )
            total_value = sum(trips.mapped('amount'))
            currency = sheet.currency_id or self.env.company.currency_id
            remaining = other
            ordered = trips.sorted(lambda t: (t.date or fields.Date.today(), t.id or 0))
            for index, trip in enumerate(ordered):
                if index == len(ordered) - 1:
                    share = remaining
                elif total_qty:
                    share = currency.round(other * trip.quantity / total_qty)
                elif total_value:
                    share = currency.round(other * trip.amount / total_value)
                else:
                    share = currency.round(other / len(ordered))
                remaining -= share
                trip.allocated_amount = share
                trip.total_cost = trip.amount + share
                trip.unit_cost = trip.total_cost / trip.quantity if trip.quantity else 0.0
        for trip in self.filtered(lambda t: not t.sheet_id):
            trip.allocated_amount = 0.0
            trip.total_cost = trip.amount
            trip.unit_cost = trip.amount / trip.quantity if trip.quantity else 0.0
