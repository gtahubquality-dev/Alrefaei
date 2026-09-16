"""Shared BOQ constants."""

BOQ_ITEM_TYPES = [
    ("main", "Main Item"),
    ("material", "Material"),
    ("equipment", "Equipment"),
    ("subcontractor", "Subcontractor"),
]


def form_action(name, res_model, res_id):
    """Return a standard form action."""
    return {
        "type": "ir.actions.act_window",
        "name": name,
        "res_model": res_model,
        "res_id": res_id,
        "view_mode": "form",
    }
