"""Shared field declarations and workflow helpers for construction records."""

from odoo import Command, _, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

from .construction_finance import DEDUCTION_FREQUENCIES
from .runtime import model_attribute


def invoice_field():
    """Invoice field."""
    return fields.Many2one(
        'construction.subcontract.invoice',
        string='Invoice',
        required=True,
        ondelete='cascade',
        index=True,
    )


def reference_field():
    """Reference field."""
    return fields.Char(
        string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New')
    )


def project_field(*, domain="[('state', 'in', ('running', 'suspended'))]"):
    """Project field."""
    return fields.Many2one(
        'construction.project',
        string='Project',
        required=True,
        index=True,
        tracking=True,
        domain=domain,
    )


def requester_field():
    """Requester field."""
    return fields.Many2one(
        'res.users', string='Requested By', default=lambda self: self.env.user, readonly=True
    )


def workflow_status_field(selection):
    """Workflow status field."""
    return fields.Selection(
        selection, string='Status', default='draft', required=True, tracking=True, copy=False
    )


def company_field():
    """Company field."""
    return fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company
    )


def cascade_project_field():
    """Cascade project field."""
    return fields.Many2one(
        'construction.project',
        string='Project',
        required=True,
        index=True,
        ondelete='cascade',
        tracking=True,
    )


def restrict_project_field():
    """Restrict project field."""
    return fields.Many2one(
        'construction.project',
        string='Project',
        required=True,
        index=True,
        ondelete='restrict',
        tracking=True,
    )


def deduction_calculation_field():
    """Deduction calculation field."""
    return fields.Selection(
        [('percent', 'Percentage of Gross Amount'), ('fixed', 'Fixed Amount per Invoice')],
        string='Calculation',
        required=True,
        default='percent',
    )


def material_line_field():
    """Material line field."""
    return fields.Many2one(
        'construction.material.request.line',
        string='Material Request Line',
        index='btree_not_null',
        copy=False,
    )


def construction_project_field():
    """Construction project field."""
    return fields.Many2one(
        'construction.project',
        string='Construction Project',
        index='btree_not_null',
        copy=False,
        check_company=True,
    )


def deduction_frequency_field():
    """Deduction frequency field."""
    return fields.Selection(DEDUCTION_FREQUENCIES, string='Applied', required=True, default='every')


def contract_field():
    """Contract field."""
    return fields.Many2one(
        'construction.subcontract', string='Contract', required=True, ondelete='cascade', index=True
    )


def owner_invoice_field():
    """Owner invoice field."""
    return fields.Many2one(
        'construction.owner.invoice',
        string='Owner Invoice',
        required=True,
        ondelete='cascade',
        index=True,
    )


def append_invoice_deductions(lines, invoice, project, distribution):
    """Append invoice deductions."""
    for deduction in invoice.deduction_ids:
        if float_is_zero(deduction.amount, precision_rounding=invoice.currency_id.rounding):
            continue
        lines.append(
            Command.create(
                {
                    'name': deduction.name,
                    'quantity': 1.0,
                    'price_unit': -deduction.amount,
                    'account_id': model_attribute(project, '_check_invoice_line_account')(
                        deduction.account_id, deduction.name
                    ).id,
                    'tax_ids': [Command.clear()],
                    'analytic_distribution': distribution,
                }
            )
        )


def apply_deduction_type(self):
    """Apply deduction type."""
    for deduction in self:
        if deduction.type_id:
            deduction.name = deduction.type_id.name
            deduction.kind = deduction.type_id.kind
            deduction.calculation = deduction.type_id.calculation
            deduction.value = deduction.type_id.value
            deduction.frequency = deduction.type_id.frequency
            deduction.account_id = deduction.type_id.account_id
            deduction.refundable = deduction.type_id.refundable


def check_deduction_values(self):
    """Check deduction values."""
    for deduction in self:
        if deduction.value < 0:
            raise ValidationError(_('The deduction value cannot be negative.'))
        if deduction.calculation == 'percent' and deduction.value > 100:
            raise ValidationError(_('A percentage deduction cannot exceed 100%.'))


def check_deduction_amounts(self):
    """Check deduction amounts."""
    for deduction in self:
        if deduction.amount < 0:
            raise ValidationError(_('Deduction amounts cannot be negative.'))


def check_change_order_editable(self, orders):
    """Check change order editable."""
    if self.env.su:
        return
    if any((order.state != 'draft' for order in orders)):
        raise UserError(_('Only the lines of a draft change order can be changed.'))


def compute_deduction_amount(self, gross_amount):
    """Compute deduction amount."""
    self.ensure_one()
    if self.calculation == 'percent':
        return self.currency_id.round(gross_amount * self.value / 100.0)
    return self.currency_id.round(self.value) if gross_amount > 0 else 0.0


def active_contract_field():
    """Link an amendment or invoice to an active subcontract."""
    return fields.Many2one(
        'construction.subcontract',
        string='Contract',
        required=True,
        index=True,
        domain="[('state', '=', 'active')]",
        tracking=True,
    )


def contract_related_field(field_name, label, *, store=True):
    """Declare a related subcontract field on an amendment or invoice."""
    options = {'store': True} if store else {}
    return fields.Many2one(related=f'contract_id.{field_name}', string=label, **options)


def project_subcontract_field(**options):
    """Limit subcontract selection to the record's project."""
    return fields.Many2one(
        'construction.subcontract',
        string='Subcontract',
        index=True,
        domain="[('project_id', '=', project_id)]",
        **options,
    )


def apply_component_product(components):
    """Copy product details to a BOQ or change-order component."""
    for component in components:
        if component.product_id:
            component.name = component.product_id.display_name
            component.uom_id = component.product_id.uom_id
            if not component.unit_cost:
                component.unit_cost = component.product_id.standard_price


def reset_cancelled_requests(self, **values):
    """Reset cancelled requests and clear the supplied workflow values."""
    for request in self:
        if request.state != 'cancelled':
            raise UserError(_('Only cancelled requests can be reset to draft.'))
    self.write({'state': 'draft', **values})
    return True


def analytic_lines_action(account, title):
    """Open the analytic items posted against a cost center."""
    return {
        'type': 'ir.actions.act_window',
        'name': title,
        'res_model': 'account.analytic.line',
        'view_mode': 'list,pivot',
        'domain': [(model_attribute(account.plan_id, '_column_name')(), '=', account.id)],
    }
