"""Construction Management 19.0.1.17.0.

1. Projects started once keep their BOQ locked: also those cancelled with only subcontracts, equipment requests
   or change orders.
2. Subcontractor invoices approved before an amendment changed the unit price keep the price of their approval
   (19.0.1.16.0 stored the unit price of the invoice lines from the current contract price).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

APPROVED_STATES = ('site_approved', 'mgmt_approved', 'finance_approved', 'cancelled')


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE construction_project p SET was_started = TRUE
         WHERE COALESCE(p.was_started, FALSE) = FALSE AND (
               p.state NOT IN ('draft', 'cancelled')
            OR EXISTS (SELECT 1 FROM construction_boq_history h WHERE h.project_id = p.id)
            OR EXISTS (SELECT 1 FROM construction_owner_invoice i WHERE i.project_id = p.id)
            OR EXISTS (SELECT 1 FROM construction_material_request r WHERE r.project_id = p.id)
            OR EXISTS (SELECT 1 FROM construction_subcontract s WHERE s.project_id = p.id AND s.state != 'draft')
            OR EXISTS (SELECT 1 FROM construction_equipment_request e WHERE e.project_id = p.id)
            OR EXISTS (SELECT 1 FROM construction_change_order c WHERE c.project_id = p.id))
    """)
    _logger.info("Construction Management: %s more projects marked as started", cr.rowcount)

    env = api.Environment(cr, SUPERUSER_ID, {})
    InvoiceLine = env['construction.subcontract.invoice.line']
    lines = InvoiceLine.search([('invoice_id.state', 'in', APPROVED_STATES)])
    fixed = 0
    for line in lines:
        approved_on = line.invoice_id.site_approved_date
        if not approved_on:
            continue

        amendment_line = env['construction.subcontract.amendment.line'].search([
            ('contract_line_id', '=', line.contract_line_id.id), ('amendment_id.state', '=', 'approved'),
            ('amendment_id.approved_date', '>=', approved_on), ('new_unit_price', '!=', 0),
            ('previous_unit_price', '!=', 0)], order='id asc', limit=1)
        price = amendment_line.previous_unit_price if amendment_line else line.contract_line_id.unit_price
        bill_line = line.invoice_id.move_id.invoice_line_ids.filtered(
            lambda l: l.quantity and l.construction_boq_item_id == line.contract_line_id.boq_item_id)[:1]
        if bill_line and line.invoice_id.move_id.state == 'posted':
            price = bill_line.price_unit
        if line.currency_id.compare_amounts(price, line.unit_price) if line.currency_id else price != line.unit_price:
            line.unit_price = price
            fixed += 1
    env.flush_all()
    _logger.info("Construction Management: unit price of %s approved subcontractor invoice lines restored", fixed)
