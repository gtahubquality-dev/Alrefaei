"""Settings proxy for the company customization switch."""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose the customization switch on the active company settings."""

    _inherit = "res.config.settings"

    enable_free_customizations = fields.Boolean(
        related="company_id.enable_free_customizations",
        readonly=False,
    )
