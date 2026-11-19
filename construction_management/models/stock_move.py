"""Stock move for construction management."""

from odoo import models

from .construction_common import material_line_field


class StockMove(models.Model):
    """Stock move."""

    _inherit = 'stock.move'

    construction_material_line_id = material_line_field()
