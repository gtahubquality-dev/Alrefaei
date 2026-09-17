"""Current-company helper fields for product template views."""

from odoo import fields, models


class ProductTemplate(models.Model):
    """Expose the active company's customization flag to product template forms."""

    _inherit = "product.template"

    free_customizations_enabled = fields.Boolean(
        compute="_compute_free_customizations_enabled",
    )

    def _compute_free_customizations_enabled(self):
        enabled = self.env.company.enable_free_customizations
        for template in self:
            template.free_customizations_enabled = enabled
