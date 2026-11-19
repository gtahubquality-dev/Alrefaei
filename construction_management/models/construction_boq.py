"""Construction boq for construction management."""

COMPONENT_TYPES = [
    ('material', 'Materials'),
    ('equipment', 'Equipment'),
    ('subcontract', 'Subcontractors'),
    ('labor', 'External Labor'),
]
COST_TYPES = COMPONENT_TYPES + [('other', 'Other Costs')]
