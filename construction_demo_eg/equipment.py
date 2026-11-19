"""Egyptian construction demo equipment workflows."""

from datetime import timedelta
from dateutil.relativedelta import relativedelta
from . import payments, utils
from .demo_data import MACHINES
from .state import DateRange


def asset_values(builder, name, value, acquisition_date):
    """With the Assets bridge (construction_equipment_asset), company owned equipment must
    be linked to a fixed asset of the Assets app: create it (draft)."""
    equipment_model = builder.context.env['construction.equipment']
    if 'asset_id' not in equipment_model._fields:
        return {}
    asset_model = builder.context.env[equipment_model._fields['asset_id'].comodel_name].sudo()
    vals = {
        'name': name,
        'company_id': builder.context.company.id,
        'original_value': value,
        'acquisition_date': acquisition_date,
    }
    optional = {
        'account_asset_id': asset_account(builder, 'fixed'),
        'account_depreciation_id': asset_account(builder, 'depreciation'),
        'account_depreciation_expense_id': asset_account(builder, 'expense'),
        'journal_id': builder.accounting.misc.id,
        'method_number': 60,
        'method_period': '1',
    }
    vals.update(
        {key: value for (key, value) in optional.items() if key in asset_model._fields and value}
    )
    vals = {key: value for (key, value) in vals.items() if key in asset_model._fields}
    return {'asset_id': asset_model.create(vals).id}


def asset_account(builder, kind):
    """Asset account."""
    if not hasattr(builder.accounting, 'asset_accounts'):
        builder.accounting.asset_accounts = {
            'fixed': utils.ensure_account(builder, '109201', 'معدات وآلات', 'asset_fixed').id,
            'depreciation': utils.ensure_account(
                builder, '109202', 'مجمع إهلاك المعدات والآلات', 'asset_fixed'
            ).id,
            'expense': utils.ensure_account(
                builder, '409201', 'إهلاك المعدات والآلات', 'expense_depreciation'
            ).id,
        }
    return builder.accounting.asset_accounts[kind]


def setup_equipment(builder):
    """Setup equipment."""
    equipment_model = builder.context.env['construction.equipment']
    builder.equipment.machines = equipment_model
    for name, code, category, cost, depreciation, diesel, model in MACHINES:
        acquisition = builder.context.today - relativedelta(years=builder.context.rng.randint(1, 6))
        builder.equipment.machines |= equipment_model.create(
            {
                'name': name,
                'code': utils.free(builder, 'construction.equipment', 'code', code),
                'category': category,
                'equipment_type': model,
                'ownership': 'owned',
                'track_in_inventory': False,
                'acquisition_date': acquisition,
                'purchase_value': cost * 4000,
                'depreciation_amount': depreciation * 180,
                **asset_values(builder, name, cost * 4000, acquisition),
                'operating_cost_per_hour': cost,
                'depreciation_per_hour': depreciation,
                'diesel_per_hour': diesel,
                'diesel_price': 15.5 if diesel else 0.0,
                'serial_number': f'SN-{code!s}-{int(builder.context.rng.randint(1000, 9999)):04d}',
            }
        )
    builder.equipment.machines_free = list(builder.equipment.machines)
    builder.equipment.rented = equipment_model
    for name, code in (
        ('ونش متحرك 50 طن (إيجار)', 'RC-01'),
        ('ونش متحرك 70 طن (إيجار)', 'RC-02'),
        ('حفار إيجار - كوماتسو', 'RE-01'),
        ('مضخة خرسانة (إيجار)', 'RP-01'),
        ('لودر إيجار - كاتربيلر', 'RL-02'),
        ('ونش برجي (إيجار)', 'RT-01'),
        ('ونش برجي (إيجار) - رافعة 2', 'RT-02'),
        ('جريدر إيجار', 'RG-01'),
        ('هراس إيجار', 'RR-01'),
        ('مضخة خرسانة (إيجار) 2', 'RP-02'),
    ):
        builder.equipment.rented |= equipment_model.create(
            {
                'name': name,
                'code': utils.free(builder, 'construction.equipment', 'code', code),
                'category': 'equipment',
                'ownership': 'rented',
                'track_in_inventory': False,
            }
        )
    builder.equipment.rented_free = list(builder.equipment.rented)


def take_machine(builder, date, name):
    """Free company machine of the kind requested in the BOQ."""
    kind = utils.kind(name)
    for machine in builder.equipment.machines_free:
        if (
            utils.kind(machine.name) == kind
            and builder.equipment.machine_available.get(machine.id, date - timedelta(days=1)) < date
        ):
            builder.equipment.machines_free.remove(machine)
            return machine
    return builder.context.env['construction.equipment']


def requested_hours(builder, component):
    """Hours already requested on a BOQ equipment (works with every version of the modules)."""
    requests = builder.context.env['construction.equipment.request'].search(
        [
            ('boq_component_id', '=', component.id),
            ('state', 'not in', ('draft', 'cancelled', 'rejected')),
        ]
    )
    return sum(requests.mapped('requested_quantity'))


def rented_of_kind(builder, name):
    """Rented of kind."""
    kind = utils.kind(name)
    for equipment in builder.equipment.rented_free:
        if utils.kind(equipment.name) == kind:
            return equipment
    return builder.context.env['construction.equipment']


def assign_equipment(builder, project, start, end, rent=True):
    """Equipment."""
    requests = builder.context.env['construction.equipment.request']
    components = project.boq_item_ids.component_ids.filtered(
        lambda c: c.component_type == 'equipment'
    )
    for number, component in enumerate(components[:2]):
        date_from = start + timedelta(days=7 + 20 * number)
        machine = take_machine(builder, date_from, component.name)
        if not machine:
            continue
        date_from = max(
            date_from,
            builder.equipment.machine_available.get(machine.id, date_from) + timedelta(days=1),
        )
        if date_from >= end - timedelta(days=14):
            builder.equipment.machines_free.append(machine)
            continue
        request = builder.context.env['construction.equipment.request'].create(
            {
                'project_id': project.id,
                'description': component.name,
                'boq_component_id': component.id,
                'requested_quantity': min(component.quantity, 400),
                'date_from': date_from,
            }
        )
        request.action_submit()
        if request.state == 'to_approve':
            request.action_approve()
        request.equipment_id = machine
        request.action_assign()
        movement = request.movement_id
        movement.move_datetime = utils.at(date_from, 7)
        movement.action_done()
        if movement.state == 'in_transit':
            movement.action_confirm_arrival()
        requests |= request
        record_usage(
            builder, machine, project, DateRange(date_from, end), request.requested_quantity
        )
        record_expenses(builder, machine, DateRange(date_from, end))
    uncovered = [
        (c, rented_of_kind(builder, c.name))
        for c in components
        if c.effective_quantity - requested_hours(builder, c) >= 8
    ]
    uncovered = [(c, e) for (c, e) in uncovered if e]
    if rent and uncovered:
        requests |= rent_equipment(builder, project, start, end, uncovered)
    return requests


def release(builder, request, date):
    """Release."""
    machine = request.equipment_id
    request.action_release()
    request.date_to = date
    movement = request.return_movement_id
    if movement and movement.state == 'draft':
        movement.move_datetime = utils.at(date, 16)
        movement.action_done()
    if movement and movement.state == 'in_transit':
        movement.action_confirm_arrival()
    if machine:
        builder.equipment.machine_available[machine.id] = date
        builder.equipment.machines_free.append(machine)


def record_usage(builder, machine, project, period, requested_quantity):
    """Record owned machine usage with the original seeded quantities and dates."""
    day = period.start + timedelta(days=3)
    budget = requested_quantity * builder.context.rng.choice([0.5, 0.6, 0.7, 0.8, 0.9, 1.08])
    worked = 0.0
    while day < period.end and worked < budget:
        usage = builder.context.env['construction.equipment.usage'].create(
            {
                'equipment_id': machine.id,
                'project_id': project.id,
                'date': day,
                'hours': builder.context.rng.choice([6, 7, 8, 9, 10]),
                'note': builder.context.rng.choice(
                    ['تشغيل يومي', 'صب خرسانة', 'حفر وتحميل', 'رفع حديد وشدات']
                ),
            }
        )
        usage.action_post()
        worked += usage.hours
        day += timedelta(days=builder.context.rng.choice([3, 4, 6, 8]))


def record_expenses(builder, machine, period):
    """Record maintenance and fuel expenses for the original operating period."""
    for expense_type, amount, vendor in (
        ('fuel', builder.context.rng.randint(8000, 25000), 'fuel'),
        ('maintenance', builder.context.rng.randint(5000, 18000), 'workshop'),
        ('oil', builder.context.rng.randint(2000, 6000), 'fuel'),
    ):
        expense_date = min(
            period.start + timedelta(days=builder.context.rng.randint(15, 90)),
            period.end - timedelta(days=1),
        )
        if expense_date <= period.start:
            continue
        expense = builder.context.env['construction.equipment.expense'].create(
            {
                'equipment_id': machine.id,
                'expense_type': expense_type,
                'amount': amount,
                'vendor_id': builder.partners.vendors[vendor].id,
                'expense_datetime': utils.at(expense_date, 12),
                'vendor_reference': f'F-{int(builder.context.rng.randint(1000, 99999)):05d}',
            }
        )
        expense.action_submit()
        expense.action_create_bill()
        expense.move_id.action_post()
    if period.end >= builder.context.today - timedelta(days=1):
        expense = builder.context.env['construction.equipment.expense'].create(
            {
                'equipment_id': machine.id,
                'expense_type': 'fuel',
                'amount': builder.context.rng.randint(4000, 9000),
                'vendor_id': builder.partners.vendors['fuel'].id,
                'expense_datetime': utils.at(
                    builder.context.today - timedelta(days=builder.context.rng.randint(1, 6)), 11
                ),
                'vendor_reference': f'F-{int(builder.context.rng.randint(1000, 99999)):05d}',
            }
        )
        expense.action_submit()
        if builder.context.rng.random() < 0.6:
            expense.action_create_bill()
            expense.move_id.action_post()


def rent_equipment(builder, project, start, end, uncovered):
    """Procure and bill the first uncovered rental machine through the existing workflow."""
    component, crane = uncovered[0]
    builder.equipment.rented_free.remove(crane)
    hours = round(component.effective_quantity - requested_hours(builder, component))
    request = builder.context.env['construction.equipment.request'].create(
        {
            'project_id': project.id,
            'description': f'{component.name!s} (إيجار)',
            'boq_component_id': component.id,
            'requested_quantity': hours,
            'date_from': start + timedelta(days=30),
        }
    )
    request.action_submit()
    if request.state == 'to_approve':
        request.action_approve()
    vendor = (
        builder.partners.vendors['crane']
        if 'ونش' in crane.name
        else builder.partners.vendors['rental']
    )
    request.write(
        {
            'rental_vendor_id': vendor.id,
            'rental_product_id': builder.equipment.rental_service.id,
            'rental_quantity': hours,
            'rental_price': builder.context.rng.choice([900, 1200, 1600]),
            'rented_equipment_id': crane.id,
        }
    )
    request.action_request_rental()
    order = request.purchase_order_id
    order.button_confirm()
    order.action_create_invoice()
    bill = order.invoice_ids.filtered(lambda m: m.state == 'draft')
    bill.invoice_line_ids.filtered('purchase_line_id').quantity = round(
        hours * builder.context.rng.uniform(0.4, 0.8)
    )
    bill.write(
        {'invoice_date': min(start + timedelta(days=60), end), 'ref': f'RENT-{order.name!s}'}
    )
    bill.action_post()
    payments.pay(builder, bill, bill.invoice_date + timedelta(days=20))
    return request
