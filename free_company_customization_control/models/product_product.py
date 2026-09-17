"""Current-company helper fields for product variant views."""

from odoo import fields, models


class ProductProduct(models.Model):
    """Expose the active company's customization flag to product forms."""

    _inherit = "product.product"

    free_customizations_enabled = fields.Boolean(
        compute="_compute_free_customizations_enabled",
    )

    def _compute_free_customizations_enabled(self):
        enabled = self.env.company.enable_free_customizations
        for product in self:
            product.free_customizations_enabled = enabled
