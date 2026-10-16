"""Quantities assigned from subcontractor BOQ lines."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class ConstructionSubcontractorContractLine(models.Model):
    """Subcontractor Contract Line."""

    _name = "construction.subcontractor.contract.line"
    _description = "Subcontractor Contract Line"

    contract_id = fields.Many2one(
        "construction.subcontractor.contract", required=True, ondelete="cascade",
    )
    source_line_id = fields.Many2one(
        "construction.subcontractor.boq.line", required=True, ondelete="restrict",
    )
    product_id = fields.Many2one(related="source_line_id.product_id")
    finished_product_id = fields.Many2one(related="source_line_id.finished_product_id")
    description = fields.Text(related="source_line_id.description")
    uom_id = fields.Many2one(related="source_line_id.uom_id")
    quantity = fields.Float(required=True)
    price_unit = fields.Float(string="Unit Price")
    currency_id = fields.Many2one(related="contract_id.currency_id")
    subtotal = fields.Monetary(compute="_compute_subtotal")

    @api.depends("quantity", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.constrains("source_line_id", "quantity", "contract_id")
    def _check_distribution(self):
        for line in self:
            source = line.source_line_id
            if source.subcontractor_boq_id != line.contract_id.subcontractor_boq_id:
                raise ValidationError(_(
                    "Contract lines must belong to the selected subcontractor BOQ.",
                ))
            rounding = source.uom_id.rounding or 0.01
            if line.quantity <= 0 or float_compare(
                source.distributed_quantity, source.quantity, precision_rounding=rounding,
            ) > 0:
                raise ValidationError(_(
                    "Distribute a positive quantity within the available BOQ quantity.",
                ))
