"""Shared project field declaration for fleet trip and expense lines."""

from odoo import fields


def project_field():
    """Create a fresh project field using each concrete line model compute hook."""
    return fields.Many2one(
        'construction.project',
        string='Project',
        compute='_compute_project_id',
        store=True,
        readonly=False,
    )
