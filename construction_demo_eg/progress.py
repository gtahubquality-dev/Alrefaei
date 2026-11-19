"""Egyptian construction demo progress workflows."""

from datetime import timedelta
from dateutil.relativedelta import relativedelta
from . import equipment, payments, utils
from .state import ProgressStep


def progress(builder, project, contracts, period, full=False):
    """Monthly progress: owner invoices and subcontractor invoices, with their payments."""
    months = max(
        (period.end.year - period.start.year) * 12 + period.end.month - period.start.month, 1
    )
    count = min(max(months // 2, 1), 6)
    target = utils.target(project, period.start, period.end, full=full)
    done = 0.0
    for number in range(1, count + 1):
        date = min(period.start + relativedelta(months=round(months * number / count)), period.end)
        fraction = target * number / count - done
        done += fraction
        last = number == count
        step = ProgressStep(date, fraction, full, last, number)
        owner_progress(builder, project, step)
        subcontract_progress(builder, contracts, step)


def close_site(builder, requests, contracts, end):
    """Close site."""
    for request in requests:
        if (
            'rental_contract_id' in request._fields
            and request.rental_contract_id
            and (request.rental_contract_id.state == 'running')
        ):
            request.rental_contract_id.action_return()
        elif request.state == 'assigned':
            equipment.release(builder, request, end)
    for contract in contracts:
        if contract.state == 'active':
            contract.action_close()


def owner_progress(builder, project, step):
    """Generate, approve, post, and optionally pay one owner progress invoice."""
    vals = {'project_id': project.id, 'date': step.date}
    if 'invoice_type' in builder.context.env['construction.owner.invoice']._fields:
        vals['invoice_type'] = 'progress'
    invoice = builder.context.env['construction.owner.invoice'].create(vals)
    invoice.action_generate_lines()
    for line in invoice.line_ids:
        qty = line.boq_quantity * step.fraction
        if step.full and step.last:
            qty = line.boq_quantity - line.previous_quantity
        line_vals: dict[str, float] = {'current_quantity': round(max(qty, 0.0), 2)}
        if step.number == 2 and line == invoice.line_ids[:1] and (not step.full):
            line_vals['unit_price'] = round(line.unit_price * 1.08, 2)
        line.write(line_vals)
    invoice.action_refresh()
    invoice.action_submit()
    if invoice.state == 'to_approve':
        invoice.action_approve_senior()
    elif invoice.state == 'to_approve_exceptional':
        invoice.action_approve_exceptional()
    invoice.action_create_invoice()
    invoice.move_id.action_post()
    if not step.last or step.full:
        payments.pay(
            builder,
            invoice.move_id,
            step.date + timedelta(days=builder.context.rng.randint(20, 45)),
        )


def subcontract_progress(builder, contracts, step):
    """Generate, approve, post, and optionally pay subcontractor progress invoices."""
    for contract in contracts:
        sub_invoice = builder.context.env['construction.subcontract.invoice'].create(
            {'contract_id': contract.id, 'date': step.date}
        )
        for line in sub_invoice.line_ids:
            qty = line.contract_line_id.quantity * step.fraction
            if step.full and step.last:
                qty = line.contract_line_id.quantity - line.previous_quantity
            line.current_quantity = round(max(qty, 0.0), 2)
        sub_invoice.action_site_approve()
        sub_invoice.action_mgmt_approve()
        sub_invoice.action_finance_approve()
        sub_invoice.move_id.write({'ref': f'SUB-{sub_invoice.name!s}'})
        sub_invoice.move_id.action_post()
        if not step.last or step.full:
            payments.pay(
                builder,
                sub_invoice.move_id,
                step.date + timedelta(days=builder.context.rng.randint(15, 40)),
            )
