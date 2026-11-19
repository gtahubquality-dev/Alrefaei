"""Construction Management 19.0.1.12.0: advance payment invoices and final insurance on the owner invoices.

The new columns are created with the values of the existing invoices (progress invoices, no final insurance
withheld) so that the approved and invoiced amounts are not recomputed by the upgrade.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        ALTER TABLE construction_owner_invoice
            ADD COLUMN IF NOT EXISTS invoice_type varchar,
            ADD COLUMN IF NOT EXISTS advance_amount numeric,
            ADD COLUMN IF NOT EXISTS insurance_percent double precision,
            ADD COLUMN IF NOT EXISTS insurance_amount numeric
    """)
    cr.execute("""
        UPDATE construction_owner_invoice
           SET invoice_type = COALESCE(invoice_type, 'progress'),
               advance_amount = COALESCE(advance_amount, 0),
               insurance_percent = COALESCE(insurance_percent, 0),
               insurance_amount = COALESCE(insurance_amount, 0)
    """)
