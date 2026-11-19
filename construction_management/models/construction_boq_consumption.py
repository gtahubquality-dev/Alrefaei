"""Link of the supply documents (material requests, transfers, purchase orders, subcontracts,
workforce) to the BOQ cost components, and consumption of each BOQ component.
"""

SUBCONTRACT_EXECUTED_STATES = ('site_approved', 'mgmt_approved', 'finance_approved')
REQUEST_LINE_STATES = ('to_approve', 'approved', 'done')
CERTIFIED_STATES = ('approved', 'invoiced')
