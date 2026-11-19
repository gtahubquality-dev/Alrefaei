"""Egyptian construction demo payments workflows."""

from operator import methodcaller


def pay(builder, move, date):
    """Pay."""
    date = min(date, builder.context.today)
    if (
        move.state != 'posted'
        or move.payment_state in ('paid', 'in_payment')
        or (not move.amount_residual)
    ):
        return
    methodcaller('_create_payments')(
        builder.context.env['account.payment.register']
        .with_context(active_model='account.move', active_ids=move.ids)
        .create({'journal_id': builder.accounting.bank.id, 'payment_date': date})
    )
