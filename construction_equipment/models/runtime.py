"""Runtime dispatch helpers for dynamically registered Odoo models."""

from operator import attrgetter, methodcaller

MODEL_NAME = attrgetter('_name')


def call_method(record, method_name, *args, **kwargs):
    """Dispatch to the registered record implementation, including inherited overrides."""
    return methodcaller(method_name, *args, **kwargs)(record)
