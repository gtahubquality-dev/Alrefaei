"""Shared accounting details for construction invoice adjustments."""

from odoo import Command

from .runtime import model_attribute


def adjustment_account(project, field_name, label):
    """Resolve and validate the configured account for an adjustment."""
    account = model_attribute(project, '_get_company_account')(field_name)
    return model_attribute(project, '_check_invoice_line_account')(account, label)


def adjustment_line(name, amount, account, distribution, tax_command=None):
    """Prepare the negative, one-unit invoice line for a deduction."""
    return Command.create(
        {
            'name': name,
            'quantity': 1.0,
            'price_unit': -amount,
            'account_id': account.id,
            'tax_ids': [Command.clear() if tax_command is None else tax_command],
            'analytic_distribution': distribution,
        }
    )


def journal_entry_action(move):
    """Open an existing accounting move in form view."""
    return {
        'type': 'ir.actions.act_window',
        'res_model': 'account.move',
        'res_id': move.id,
        'view_mode': 'form',
    }
