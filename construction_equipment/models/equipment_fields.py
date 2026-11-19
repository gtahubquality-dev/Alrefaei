"""Shared field declarations for equipment operation records."""

from odoo import _, fields


def reference_field():
    """Create a fresh reference field with the shared equipment defaults."""
    return fields.Char(
        string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New')
    )


def tracked_equipment_field():
    """Create a fresh tracked equipment field with the shared equipment defaults."""
    return fields.Many2one(
        'construction.equipment', string='Equipment', required=True, index=True, tracking=True
    )


def status_field(selection):
    """Create a fresh status field with the shared equipment defaults."""
    return fields.Selection(
        selection, string='Status', default='draft', required=True, tracking=True, copy=False
    )


def request_field(help_text):
    """Create a fresh request field with the shared equipment defaults."""
    return fields.Many2one(
        'construction.equipment.request',
        string='Equipment Request',
        compute='_compute_request_id',
        store=True,
        readonly=False,
        index='btree_not_null',
        domain="[('project_id', '=', project_id)]",
        help=help_text,
    )
