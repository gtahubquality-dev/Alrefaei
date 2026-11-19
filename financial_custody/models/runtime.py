"""Resolve internal hooks on Odoo recordsets at runtime."""


def model_attribute(record, name):
    """Resolve a model attribute, preserving inherited overrides and descriptors."""
    return getattr(record, name)
