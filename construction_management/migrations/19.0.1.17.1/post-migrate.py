"""Construction Management 19.0.1.17.1: terms of the customer contracts signed before 19.0.1.17.0.

19.0.1.17.0 stores the contract terms (frozen at signature); the columns were created empty for the contracts
already signed, which then kept 0. They get the terms of their project (the terms they were signed with: the
financial terms of a started project are locked).
"""
import logging

_logger = logging.getLogger(__name__)

TERMS = ('advance_payment_percent', 'advance_payment_amount', 'advance_deduction_percent',
         'guarantee_percent', 'final_insurance_percent', 'final_insurance_amount')


def migrate(cr, version):
    if not version:
        return
    assignments = ', '.join(f'{name} = p.{name}' for name in TERMS)
    empty = ' AND '.join(f'COALESCE(c.{name}, 0) = 0' for name in TERMS)
    cr.execute(f"""
        UPDATE construction_customer_contract c
           SET {assignments}
          FROM construction_project p
         WHERE p.id = c.project_id
           AND {empty}
    """)
    _logger.info('Construction Management: terms of %s customer contracts restored', cr.rowcount)
