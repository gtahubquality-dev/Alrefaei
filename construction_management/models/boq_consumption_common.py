"""Shared BOQ component and stock movement rules."""

from odoo import fields

from .runtime import model_attribute


def boq_component_field(label, domain, help_text):
    """Create a computed, editable link to a BOQ component."""
    return fields.Many2one(
        'construction.boq.component',
        string=label,
        index='btree_not_null',
        compute='_compute_boq_component_id',
        store=True,
        readonly=False,
        precompute=True,
        domain=domain,
        help=help_text,
    )


def done_stock_moves(env, domain):
    """Find completed moves matching the caller's stock filters."""
    return env['stock.move'].sudo().search([('state', '=', 'done'), *domain])


def site_stock_move_domain(view, date_from=False, date_to=False):
    """Match moves touching the warehouse tree within an inclusive date range."""
    domain = [
        '|',
        ('location_dest_id', 'child_of', view.id),
        ('location_id', 'child_of', view.id),
    ]
    if date_from:
        domain.append(('date', '>=', fields.Datetime.to_datetime(date_from)))
    if date_to:
        domain.append(
            ('date', '<', fields.Datetime.to_datetime(fields.Date.add(date_to, days=1)))
        )
    return domain


def site_stock_move_sign(move, prefix, outbound_usages):
    """Return +1 for receipts, -1 for qualifying returns, and 0 otherwise."""
    to_site = (move.location_dest_id.parent_path or '').startswith(prefix)
    from_site = (move.location_id.parent_path or '').startswith(prefix)
    if to_site and not from_site:
        return 1.0
    if from_site and not to_site and move.location_dest_id.usage in outbound_usages:
        return -1.0
    return 0.0


def site_stock_move_value(move, project):
    """Use stock valuation when present, otherwise use the project's company cost."""
    product = move.product_id
    quantity = model_attribute(move.product_uom, '_compute_quantity')(
        move.quantity, product.uom_id
    )
    return (
        abs(move.value)
        if 'value' in move._fields and move.value
        else quantity * product.with_company(project.company_id).standard_price
    )
