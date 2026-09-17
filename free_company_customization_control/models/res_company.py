"""Company switch for custom free module behavior."""

from odoo import fields, models


class ResCompany(models.Model):
    """Store whether company-specific free customizations are active."""

    _inherit = "res.company"

    enable_free_customizations = fields.Boolean(
        string="Enable Free Customizations",
        help="Enable the custom Sales, Purchase, and Product behavior from the free addons.",
    )
