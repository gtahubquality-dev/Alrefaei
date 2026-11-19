"""Stock picking for construction management."""

from odoo import _
from odoo import fields
from odoo import models

from .runtime import model_attribute


class StockPicking(models.Model):
    """Stock picking."""

    _inherit = 'stock.picking'

    construction_project_id = fields.Many2one(
        'construction.project',
        string='Construction Project',
        index='btree_not_null',
        copy=True,
        check_company=True,
    )
    construction_material_request_id = fields.Many2one(
        'construction.material.request', string='Material Request', readonly=True, copy=False
    )

    def action_cancel(self):
        """Cancel."""
        res = super().action_cancel()
        cancelled = self.filtered(lambda p: p.state == 'cancel').sudo()
        for picking in cancelled:
            request = picking.construction_material_request_id
            if request.state == 'done' and request.picking_id == picking:
                model_attribute(request, '_reopen_after_document_cancel')(
                    _('Transfer %s', picking.name)
                )
        return res
