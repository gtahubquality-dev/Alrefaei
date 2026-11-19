"""Construction equipment init support."""

from datetime import datetime, time
from . import models

DEFERRED_PARAM = 'construction_equipment.migrate_datetimes'


def _post_init_hook(env):
    """Finish the data migration of databases upgraded from Construction Management <
    19.0.1.2.0, where movements / expenses only had a date (see
    construction_management migration 19.0.1.2.0)."""
    param_model = env['ir.config_parameter'].sudo()
    if not param_model.get_param(DEFERRED_PARAM):
        return
    movement_model = env['construction.equipment.movement']
    movements = movement_model.search([('date', '!=', False)])
    with env.protecting([movement_model._fields['date']], movements):
        for movement in movements:
            movement.move_datetime = datetime.combine(movement.date, time(12, 0))
    expense_model = env['construction.equipment.expense']
    expenses = expense_model.search([('date', '!=', False)])
    with env.protecting(
        [expense_model._fields['date'], expense_model._fields['project_id']], expenses
    ):
        for expense in expenses:
            expense.expense_datetime = datetime.combine(expense.date, time(12, 0))
    param_model.search([('key', '=', DEFERRED_PARAM)]).unlink()
