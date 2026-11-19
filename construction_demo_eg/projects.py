"""Egyptian construction demo projects workflows."""

from datetime import timedelta
from dateutil.relativedelta import relativedelta
from odoo import Command
from odoo.exceptions import UserError
from . import equipment, materials, payments, progress, subcontracts, utils
from .demo_data import BOQ_TEMPLATES
from .demo_logging import LOGGER
from .state import DateRange


def tenders_lost(builder):
    """Tenders still under study or lost (bidding pipeline)."""
    uom = builder.context.root_env.ref('uom.product_uom_cubic_meter')
    for name, owner, state in (
        ('مدرسة تجريبية - الفيوم', 6, 'lost'),
        ('مجمع إداري - العبور', 4, 'submitted'),
        ('توسعة مصنع - السادات', 2, 'study'),
    ):
        tender = builder.context.env['bidding.tender'].create(
            {
                'name': name,
                'partner_id': builder.partners.owners[owner].id,
                'start_date': builder.context.today + relativedelta(months=2),
                'duration_months': 12,
                'boq_item_ids': [
                    Command.create(
                        {
                            'code': '01',
                            'name': 'أعمال خرسانية',
                            'uom_id': uom.id,
                            'quantity': 900,
                            'unit_price': 9800,
                            'weight_percent': 100,
                        }
                    )
                ],
            }
        )
        if state == 'study':
            tender.action_start_study()
        else:
            tender.action_submit()
            if state == 'lost':
                tender.action_mark_lost()


def boq_values(builder, template, scale):
    """Boq values."""
    items = []
    for code, name, uom_xmlid, base_qty, components in BOQ_TEMPLATES[template]:
        quantity = max(round(base_qty * scale * builder.context.rng.uniform(0.85, 1.15)), 1)
        comp_vals, unit_cost = boq_components(builder, components, quantity, uom_xmlid)
        unit_price = round(unit_cost * builder.context.rng.uniform(1.15, 1.3), -1)
        items.append(
            {
                'code': code,
                'name': name,
                'uom_id': builder.context.root_env.ref(uom_xmlid).id,
                'quantity': quantity,
                'unit_price': unit_price,
                'components': comp_vals,
            }
        )
    total = sum((i['quantity'] * i['unit_price'] for i in items))
    for item in items:
        item['weight_percent'] = round(item['quantity'] * item['unit_price'] / total * 100, 2)
    items[-1]['weight_percent'] = round(
        items[-1]['weight_percent'] + round(100 - sum((i['weight_percent'] for i in items)), 2), 2
    )
    return items


def deductions(builder, index):
    """Deductions."""
    a = builder.accounting.accounts
    ref = builder.context.root_env.ref
    lines = [
        {
            'type_id': ref('construction_management.deduction_type_withholding').id,
            'name': 'ضريبة خصم من المنبع 1%',
            'kind': 'tax',
            'calculation': 'percent',
            'value': 1,
            'applies_to': 'owner',
            'account_id': a['wht_owner'].id,
        },
        {
            'name': 'دمغة نقابة المهندسين 0.5%',
            'kind': 'fee',
            'calculation': 'percent',
            'value': 0.5,
            'applies_to': 'owner',
            'account_id': a['stamp'].id,
        },
        {
            'name': 'ضريبة خصم وإضافة 1% (مقاولين)',
            'kind': 'tax',
            'calculation': 'percent',
            'value': 1,
            'applies_to': 'subcontractor',
            'account_id': a['wht_sub'].id,
        },
    ]
    if index % 2 == 0:
        lines.append(
            {
                'name': 'تأمينات اجتماعية 2.5%',
                'kind': 'fee',
                'calculation': 'percent',
                'value': 2.5,
                'applies_to': 'owner',
                'account_id': a['social'].id,
            }
        )
        lines.append(
            {
                'name': 'تأمينات اجتماعية مقاولين 2%',
                'kind': 'fee',
                'calculation': 'percent',
                'value': 2,
                'applies_to': 'subcontractor',
                'account_id': a['social_sub'].id,
            }
        )
    if index % 3 == 0:
        lines.append(
            {
                'type_id': ref('construction_management.deduction_type_suspense').id,
                'name': 'تعليات 2% (ترد عند الاستلام)',
                'kind': 'suspense',
                'calculation': 'percent',
                'value': 2,
                'applies_to': 'owner',
                'account_id': a['suspense'].id,
                'refundable': True,
            }
        )
    if index % 4 == 1:
        lines.append(
            {
                'type_id': ref('construction_management.deduction_type_contract_stamp').id,
                'name': 'دمغة العقد',
                'kind': 'fee',
                'calculation': 'fixed',
                'value': 7500,
                'frequency': 'once',
                'applies_to': 'owner',
                'account_id': a['stamp'].id,
            }
        )
    return [Command.create(vals) for vals in lines]


def build_project(builder, index, spec):
    """Build project."""
    start = (
        builder.context.today - relativedelta(months=spec.months_ago)
        if spec.months_ago
        else builder.context.today + relativedelta(months=1 + index % 3)
    )
    start = start.replace(day=1 if spec.months_ago else start.day)
    project = create_project(builder, index, spec, start)
    project.write(
        {
            'deduction_ids': deductions(builder, index),
            'site_engineer_id': builder.partners.engineers[
                index % len(builder.partners.engineers)
            ].id,
        }
    )
    if spec.state == 'draft':
        return project
    project.action_start()
    if 'customer_contract_id' in project._fields and project.customer_contract_id:
        project.customer_contract_id.write({'date': start})
        project.customer_contract_id.action_sign()
    elapsed = spec.months_ago
    end = (
        builder.context.today
        if spec.state in ('running', 'suspended')
        else min(
            start + relativedelta(months=spec.duration),
            builder.context.today - relativedelta(months=1),
        )
    )
    guarantees(builder, project, start)
    advance_and_insurance(builder, project, start)
    workforce(builder, project, start)
    if index % 2 == 0 and spec.state != 'final':
        change_order(builder, project, start + relativedelta(months=max(elapsed // 2, 1)))
    target = utils.target(project, start, end, full=spec.state in ('preliminary', 'final'))
    materials.materials(builder, project, start, target, over_boq=index == 0)
    requests = equipment.assign_equipment(builder, project, start, end, rent=index % 3 != 2)
    contracts = subcontracts.subcontracts(builder, project, start)
    full = spec.state in ('preliminary', 'final')
    progress.progress(builder, project, contracts, DateRange(start, end), full=full)
    labor_cost(builder, project, start, end)
    if spec.state == 'suspended':
        project.write({'suspension_date': builder.context.today - relativedelta(months=2)})
        project.action_suspend()
    elif full:
        for deduction in project.deduction_ids.filtered(
            lambda d: d.refundable and d.deducted_amount
        ):
            refund = (
                builder.context.env['construction.project.operation']
                .with_context(**deduction.action_refund()['context'])
                .create({'date': end, 'journal_id': builder.accounting.bank.id})
            )
            refund.action_post()
        project.write({'preliminary_handover_date': end})
        project.action_preliminary_handover()
        for request in requests.filtered(lambda r: r.state == 'assigned'):
            equipment.release(builder, request, end)
        if spec.state == 'final':
            progress.close_site(builder, requests, contracts, end)
            project.write({'final_handover_date': end})
            project.action_final_handover()
    return project


def guarantees(builder, project, start):
    """Guarantees."""
    guarantee_model = builder.context.env['construction.guarantee']
    bank = builder.context.rng.choice(builder.partners.banks)
    final = guarantee_model.create(
        {
            'project_id': project.id,
            'guarantee_type': 'final',
            'guarantee_form': 'bank',
            'bank_id': bank.id,
            'reference': f"LG-{project.code.replace('/', '')!s}-F",
            'amount': round(project.contract_amount * 0.05),
            'issue_date': start,
            'expiry_date': start + relativedelta(months=project.duration_months + 12),
        }
    )
    final.action_activate()
    if project.advance_payment_amount:
        advance = guarantee_model.create(
            {
                'project_id': project.id,
                'guarantee_type': 'advance',
                'guarantee_form': 'bank',
                'bank_id': bank.id,
                'reference': f"LG-{project.code.replace('/', '')!s}-A",
                'amount': project.advance_payment_amount,
                'issue_date': start,
                'expiry_date': start + relativedelta(months=project.duration_months),
            }
        )
        advance.action_activate()


def advance_and_insurance(builder, project, start):
    """Advance and insurance."""
    operation_model = builder.context.env['construction.project.operation']
    invoice_model = builder.context.env['construction.owner.invoice']
    if (
        project.advance_payment_amount
        and 'invoice_type' in invoice_model._fields
        and project.id % 2
    ):
        invoice = invoice_model.create(
            {
                'project_id': project.id,
                'invoice_type': 'advance',
                'date': start + timedelta(days=10),
            }
        )
        invoice.action_submit()
        invoice.action_create_invoice()
        invoice.move_id.action_post()
        payments.pay(builder, invoice.move_id, start + timedelta(days=31))
    elif project.advance_payment_amount:
        advance = operation_model.create(
            {
                'project_id': project.id,
                'operation_type': 'advance_received',
                'name': 'دفعة مقدمة من المالك',
                'amount': project.advance_payment_amount,
                'journal_id': builder.accounting.bank.id,
                'date': start + timedelta(days=10),
            }
        )
        advance.action_post()


def workforce(builder, project, start):
    """Workforce."""
    workforce_model = builder.context.env['construction.project.employee']
    engineer = (
        builder.context.env['hr.employee']
        .sudo()
        .create(
            {
                'name': builder.context.rng.choice(
                    [
                        'م. أحمد سامي',
                        'م. محمد عادل',
                        'م. عمرو حسين',
                        'م. ياسر فوزي',
                        'م. هشام نبيل',
                        'م. طارق منير',
                    ]
                )
                + ' - '
                + project.code,
                'job_title': 'مهندس موقع',
            }
        )
    )
    workforce_model.create(
        {
            'project_id': project.id,
            'worker_type': 'staff',
            'employee_id': engineer.id,
            'name': engineer.name,
            'job_title': engineer.job_title,
            'project_role': 'site_engineer',
            'date_start': start,
            'cost_basis': 'monthly',
            'rate': builder.context.rng.choice([18000, 22000, 25000]),
        }
    )
    for number in range(1, 4):
        workforce_model.create(
            {
                'project_id': project.id,
                'worker_type': 'external',
                'name': f'عامل {number!s} - {project.code!s}',
                'labor_supplier_id': builder.partners.vendors['labor'].id,
                'identification_no': f'2{builder.context.rng.randint(10 ** 12, 10 ** 13 - 1):013d}',
                'project_role': 'worker',
                'date_start': start,
                'cost_basis': 'daily',
                'rate': builder.context.rng.choice([350, 400, 450]),
            }
        )


def labor_cost(builder, project, start, end):
    """Labor cost."""
    month = max(start, (end - relativedelta(months=3)).replace(day=1))
    while month + relativedelta(months=1) <= end + timedelta(days=1):
        last = month + relativedelta(months=1, days=-1)
        wizard = builder.context.env['construction.labor.cost.wizard'].create(
            {'project_id': project.id, 'date_from': month, 'date_to': last}
        )
        try:
            with builder.context.env.cr.savepoint():
                wizard.action_allocate()
        except UserError as error:
            LOGGER.info(
                'Construction demo: no labor cost for %s %s: %s', project.code, month, error
            )
        month += relativedelta(months=1)


def change_order(builder, project, date):
    """Change order."""
    items = project.boq_item_ids.sorted('code')
    lines = [
        Command.create(
            {
                'change_type': 'quantity',
                'boq_item_id': items[1].id,
                'quantity': round(items[1].quantity * 0.1, 2),
            }
        ),
        Command.create(
            {
                'change_type': 'new',
                'name': 'أعمال لاندسكيب وممرات',
                'uom_id': builder.context.root_env.ref('uom.product_uom_square_meter').id,
                'quantity': 1500,
                'unit_price': 450,
                'component_ids': [
                    Command.create(
                        {
                            'component_type': 'labor',
                            'name': 'عمالة لاندسكيب',
                            'quantity': 1500,
                            'unit_cost': 330,
                        }
                    )
                ],
            }
        ),
    ]
    order = builder.context.env['construction.change.order'].create(
        {
            'project_id': project.id,
            'date': min(date, builder.context.today),
            'line_ids': lines,
            'owner_reference': f'خطاب الاستشاري رقم {project.id!s}/{date.year!s}',
            'reason': 'طلب المالك زيادة الكميات وإضافة أعمال لاندسكيب وممرات',
        }
    )
    order.action_submit()
    order.action_approve()


def create_project(builder, index, spec, start):
    """Create an awarded or direct project from the original BOQ and contract terms."""
    boq = boq_values(builder, spec.template, spec.scale)
    owner = builder.partners.owners[spec.owner_index]
    consultant = builder.partners.consultants[index % len(builder.partners.consultants)]
    terms = {
        'advance_payment_percent': [10, 15, 0, 10, 20][index % 5],
        'guarantee_percent': [5, 10][index % 2],
        'final_insurance_percent': 5,
    }
    terms['advance_deduction_percent'] = terms['advance_payment_percent']
    if spec.from_tender:
        tender = builder.context.env['bidding.tender'].create(
            {
                'name': spec.name,
                'partner_id': owner.id,
                'consultant_id': consultant.id,
                'start_date': start,
                'duration_months': spec.duration,
                'boq_item_ids': [
                    Command.create(
                        {
                            'code': item['code'],
                            'name': item['name'],
                            'uom_id': item['uom_id'],
                            'quantity': item['quantity'],
                            'unit_price': item['unit_price'],
                            'weight_percent': item['weight_percent'],
                            'component_ids': [Command.create(comp) for comp in item['components']],
                        }
                    )
                    for item in boq
                ],
            }
        )
        tender.action_submit()
        tender.action_award()
        project = builder.context.env['construction.project'].browse(
            tender.action_create_construction_project()['res_id']
        )
        project.write(dict(terms, consultant_id=consultant.id, owner_id=owner.id))
    else:
        project = builder.context.env['construction.project'].create(
            dict(
                terms,
                name=spec.name,
                partner_id=owner.id,
                owner_id=owner.id,
                consultant_id=consultant.id,
                start_date=start,
                duration_months=spec.duration,
            )
        )
        for item in boq:
            builder.context.env['construction.boq.item'].create(
                {
                    'project_id': project.id,
                    'code': item['code'],
                    'name': item['name'],
                    'uom_id': item['uom_id'],
                    'quantity': item['quantity'],
                    'unit_price': item['unit_price'],
                    'weight_percent': item['weight_percent'],
                    'component_ids': [Command.create(comp) for comp in item['components']],
                }
            )
    return project


def boq_components(builder, components, quantity, uom_xmlid):
    """Generate BOQ cost components and their combined unit cost."""
    comp_vals = []
    unit_cost = 0.0
    for comp in components:
        if comp[0] == 'material':
            product = builder.equipment.products[comp[1]]
            qty = comp[2] * quantity
            cost = product.standard_price
            comp_vals.append(
                {
                    'component_type': 'material',
                    'product_id': product.id,
                    'name': product.name,
                    'quantity': round(qty, 2),
                    'uom_id': product.uom_id.id,
                    'unit_cost': cost,
                }
            )
            unit_cost += comp[2] * cost
        elif comp[0] == 'equipment':
            hours = max(round(comp[2] * quantity), 8)
            comp_vals.append(
                {
                    'component_type': 'equipment',
                    'name': comp[1],
                    'quantity': hours,
                    'uom_id': builder.context.root_env.ref('uom.product_uom_hour').id,
                    'unit_cost': comp[3],
                }
            )
            unit_cost += hours * comp[3] / quantity
        elif comp[0] == 'subcontract':
            comp_vals.append(
                {
                    'component_type': 'subcontract',
                    'name': comp[1],
                    'quantity': quantity,
                    'uom_id': builder.context.root_env.ref(uom_xmlid).id,
                    'unit_cost': comp[3],
                    'specifications': comp[2],
                }
            )
            unit_cost += comp[3]
        else:
            comp_vals.append(
                {
                    'component_type': 'labor',
                    'name': comp[1],
                    'quantity': quantity,
                    'uom_id': builder.context.root_env.ref(uom_xmlid).id,
                    'unit_cost': comp[2],
                }
            )
            unit_cost += comp[2]
    return (comp_vals, unit_cost)
