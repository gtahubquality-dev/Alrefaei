"""Egyptian construction demo subcontracts workflows."""

from datetime import timedelta
from odoo import Command


def subcontracts(builder, project, start):
    """Subcontracts."""
    contracts = builder.context.env['construction.subcontract']
    by_sub = {}
    for component in project.boq_item_ids.component_ids.filtered(
        lambda c: c.component_type == 'subcontract'
    ):
        by_sub.setdefault(component.specifications or 'finishing', []).append(component)
    for number, (sub_key, components) in enumerate(by_sub.items()):
        partner = (
            builder.partners.subcontractors.get(sub_key)
            or builder.partners.subcontractors['finishing']
        )
        lines = [
            Command.create(
                {
                    'boq_item_id': component.item_id.id,
                    'name': component.name,
                    'quantity': component.quantity,
                    'unit_price': round(
                        component.unit_cost * builder.context.rng.uniform(0.92, 1.0), 2
                    ),
                }
            )
            for component in components
        ]
        amount = sum((c.quantity * c.unit_cost for c in components))
        contract = builder.context.env['construction.subcontract'].create(
            {
                'project_id': project.id,
                'partner_id': partner.id,
                'duration_months': 6 + number * 2,
                'date_start': start + timedelta(days=30 + 15 * number),
                'guarantee_percent': 5,
                'advance_amount': round(amount * 0.1, -2) if number % 2 == 0 else 0.0,
                'advance_deduction_percent': 10 if number % 2 == 0 else 0.0,
                'advance_journal_id': builder.accounting.bank.id,
                'line_ids': lines,
            }
        )
        contract.action_submit()
        if contract.state == 'to_approve':
            contract.action_approve()
        if contract.advance_amount:
            contract.action_pay_advance()
        contracts |= contract
    return contracts
