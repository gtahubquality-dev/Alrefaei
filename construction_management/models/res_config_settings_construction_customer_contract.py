"""Res config settings construction customer contract for construction management."""

from odoo import fields
from odoo import models


class ResConfigSettings(models.TransientModel):
    """Res config settings."""

    _inherit = 'res.config.settings'

    construction_auto_customer_contract = fields.Boolean(
        related='company_id.construction_auto_customer_contract', readonly=False
    )
    construction_customer_contract_terms = fields.Html(
        related='company_id.construction_customer_contract_terms', readonly=False
    )
