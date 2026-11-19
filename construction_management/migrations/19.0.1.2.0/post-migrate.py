from datetime import datetime, time

from odoo import SUPERUSER_ID, api

DEFERRED_PARAM = 'construction_equipment.migrate_datetimes'


def migrate(cr, version):
    """Initialize the new date & time fields from the existing dates without recomputing the
    projects already charged on recorded expenses.

    Since 19.0.1.4.0 movements and expenses belong to the Construction Equipment & Fleet module,
    which is installed after this module during the same upgrade: the conversion is then deferred
    to its installation (post_init_hook of construction_equipment)."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['construction.equipment'].search([('category', '=', False)]).write({'category': 'equipment'})
    if 'construction.equipment.movement' not in env or 'move_datetime' not in env['construction.equipment.movement']._fields:
        env['ir.config_parameter'].sudo().set_param(DEFERRED_PARAM, '1')
        return
    convert_datetimes(env)


def convert_datetimes(env):
    Movement = env['construction.equipment.movement']
    movements = Movement.search([('date', '!=', False)])
    with env.protecting([Movement._fields['date']], movements):
        for movement in movements:
            movement.move_datetime = datetime.combine(movement.date, time(12, 0))
    Expense = env['construction.equipment.expense']
    expenses = Expense.search([('date', '!=', False)])
    with env.protecting([Expense._fields['date'], Expense._fields['project_id']], expenses):
        for expense in expenses:
            expense.expense_datetime = datetime.combine(expense.date, time(12, 0))
