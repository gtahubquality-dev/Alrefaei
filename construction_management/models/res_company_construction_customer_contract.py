"""Res company construction customer contract for construction management."""

from odoo import fields
from odoo import models


class ResCompany(models.Model):
    """Res company."""

    _inherit = 'res.company'

    construction_auto_customer_contract = fields.Boolean(
        string='Customer Contract on Project Creation',
        default=True,
        help=(
            "Create the draft customer contract automatically when a construction project is"
            " created."
        ),
    )
    construction_customer_contract_terms = fields.Html(string='Default Customer Contract Terms')
