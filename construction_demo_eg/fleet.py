"""Egyptian construction demo fleet workflows."""

import base64
from datetime import timedelta
from typing import TYPE_CHECKING

from dateutil.relativedelta import relativedelta

from odoo import Command

from . import equipment, utils
from .demo_data import VEHICLES
from .state import TripContext

if TYPE_CHECKING:
    from .hooks import DemoBuilder


def setup_fleet(builder):
    """Setup fleet."""
    employee_model = builder.context.env['hr.employee'].sudo()
    builder.fleet.drivers = builder.context.env['construction.driver']
    builder.fleet.vehicles = builder.context.env['construction.equipment']
    builder.fleet.driver_employees = {}
    for index, (name, plate, category, model, color, driver_name) in enumerate(VEHICLES):
        employee = employee_model.create({'name': driver_name, 'job_title': 'سائق'})
        driver = builder.fleet.drivers.create(
            {
                'name': driver_name,
                'employee_id': employee.id,
                'license_number': utils.free(
                    builder,
                    'construction.driver',
                    'license_number',
                    f'DL-{int(3100000 + index):07d}',
                ),
                'license_type': 'درجة أولى' if category != 'private_car' else 'خاصة',
                'license_expiry': builder.context.today + timedelta(days=60 + 90 * index),
                'id_number': f'2{int(8801010100000 + index * 7919):013d}',
                'mobile': f'+2010{int(5550000 + index):08d}',
                'employment_status': 'active',
                'document_ids': [
                    Command.create(
                        {
                            'document_type': doc_type,
                            'name': label,
                            'attachment': base64.b64encode(f'{label!s} - {driver_name!s}'.encode()),
                            'attachment_name': f'{doc_type!s}.pdf',
                        }
                    )
                    for (doc_type, label) in (
                        ('license', 'رخصة القيادة'),
                        ('national_id', 'بطاقة الرقم القومي'),
                        ('health_certificate', 'الشهادة الصحية'),
                    )
                ],
            }
        )
        builder.fleet.drivers |= driver
        builder.fleet.driver_employees[driver.id] = employee
        builder.fleet.vehicles |= builder.context.env['construction.equipment'].create(
            {
                'name': name,
                'code': utils.free(
                    builder, 'construction.equipment', 'code', f'VH-{int(index + 1):02d}'
                ),
                'category': category,
                'equipment_type': model,
                'license_plate': plate,
                'color': color,
                'vin_number': f'WDB{int(93400000000000 + index * 977):014d}',
                'model_year': str(2018 + index % 6),
                'ownership': 'owned',
                'track_in_inventory': False,
                'acquisition_date': builder.context.today - relativedelta(years=1 + index % 5),
                'purchase_value': 2500000,
                'driver_id': driver.id,
                **equipment.asset_values(
                    builder,
                    name,
                    2500000,
                    builder.context.today - relativedelta(years=1 + index % 5),
                ),
            }
        )


def fleet_operations(builder):
    """Driver custodies and retroactive trip sheets distributed by quantities."""
    gravel = builder.context.root_env.ref('construction_fleet.transport_type_gravel')
    sand = builder.context.root_env.ref('construction_fleet.transport_type_sand')
    soil = builder.context.root_env.ref('construction_fleet.transport_type_soil')
    projects = builder.demo_projects.filtered(lambda p: p.state == 'running').sorted('id')
    if not projects:
        return
    for index, vehicle in enumerate(
        builder.fleet.vehicles.filtered(lambda v: v.category != 'private_car')
    ):
        employee = builder.fleet.driver_employees[vehicle.driver_id.id]
        custody = builder.context.env['custody.request'].create(
            {
                'employee_id': employee.id,
                'purpose': f'عهدة رحلات النقل - {vehicle.name!s}',
                'amount': 120000,
                'date': builder.context.today - timedelta(days=50),
            }
        )
        custody.action_submit()
        custody.action_approve()
        custody.action_pay()
        for sheet_number in range(2):
            date_from = builder.context.today - timedelta(days=(40, 6)[sheet_number])
            context = TripContext(projects, (gravel, sand, soil), date_from)
            trips = trip_lines(builder, index, sheet_number, context)
            sheet = builder.context.env['construction.vehicle.sheet'].create(
                {
                    'vehicle_id': vehicle.id,
                    'date_from': date_from,
                    'date_to': date_from + timedelta(days=2),
                    'custody_id': custody.id,
                    'trip_ids': trips,
                    'expense_ids': [
                        Command.create(
                            {
                                'expense_kind': 'freight',
                                'name': 'ناولون',
                                'amount': 2500,
                                'date': date_from,
                            }
                        ),
                        Command.create(
                            {
                                'expense_kind': 'tips',
                                'name': 'إكراميات',
                                'amount': 600,
                                'date': date_from + timedelta(days=1),
                            }
                        ),
                        Command.create(
                            {
                                'expense_kind': 'tolls',
                                'name': 'كارتة وميزان',
                                'amount': 450,
                                'date': date_from + timedelta(days=2),
                            }
                        ),
                    ],
                }
            )
            if sum((trip[2]['amount'] for trip in trips)) + 3550 > custody.balance:
                sheet.unlink()
                break
            sheet.action_submit()
            sheet.settlement_id.action_post()


def trip_lines(builder: 'DemoBuilder', index: int, sheet_number: int, context: TripContext):
    """Generate the original seeded trip lines for one vehicle sheet."""
    trips = []
    for day in range(3):
        project = context.projects[(index + day + sheet_number) % len(context.projects)]
        transport_type = context.transport_types[(index + day) % 3]
        quantity = builder.context.rng.choice([20, 25, 30, 40])
        trips.append(
            Command.create(
                {
                    'date': context.date_from + timedelta(days=day),
                    'transport_type_id': transport_type.id,
                    'project_id': project.id,
                    'quantity': quantity,
                    'amount': quantity * builder.context.rng.choice([350, 400, 450]),
                }
            )
        )
    return trips
