"""Shared declarations and accounting helpers for custody records."""

from odoo import fields


def custody_status_field(selection):
    """Create a status field with the custody workflow defaults."""
    return fields.Selection(
        selection, string='Status', default='draft', required=True, tracking=True, copy=False
    )


def create_custody_entry(env, company, values):
    """Create a journal entry under the custody's company."""
    return env['account.move'].sudo().with_company(company).create({
        'move_type': 'entry',
        **values,
    })


def custody_move_action(move):
    """Open a custody journal entry in form view."""
    return {
        'type': 'ir.actions.act_window',
        'res_model': 'account.move',
        'res_id': move.id,
        'view_mode': 'form',
    }
