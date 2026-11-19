"""Account move for construction management."""

from odoo import _
from odoo import fields
from odoo import models

from .runtime import model_attribute

from .construction_common import construction_project_field


class AccountMove(models.Model):
    """Account move."""

    _inherit = 'account.move'

    construction_project_id = construction_project_field()
    construction_owner_invoice_id = fields.Many2one(
        'construction.owner.invoice',
        string='Owner Invoice',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )
    construction_subcontract_invoice_id = fields.Many2one(
        'construction.subcontract.invoice',
        string='Subcontractor Invoice',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )

    def _construction_documents_cancelled(self):
        """The customer invoice / vendor bill generated from an owner invoice or a subcontractor
        invoice was cancelled or deleted: cancel the source document so that its quantities are
        released.
        """
        owner_invoices = self.sudo().construction_owner_invoice_id.filtered(
            lambda inv: inv.state == 'invoiced'
        )
        for invoice in owner_invoices:
            invoice.write({'state': 'cancelled'})
            invoice.message_post(
                body=_(
                    'The customer invoice was cancelled: the owner invoice is cancelled and its '
                    'quantities are released. Reset it to draft to invoice again.'
                )
            )
        sub_invoices = self.sudo().construction_subcontract_invoice_id.filtered(
            lambda inv: inv.state == 'finance_approved'
        )
        for invoice in sub_invoices:
            invoice.write({'state': 'cancelled'})
            invoice.message_post(
                body=_(
                    'The vendor bill was cancelled: the subcontractor invoice is cancelled and '
                    'its quantities are released.'
                )
            )

    def button_cancel(self):
        """Button cancel."""
        res = super().button_cancel()
        model_attribute(
            self.filtered(lambda m: m.state == 'cancel'), '_construction_documents_cancelled'
        )()
        return res

    def _construction_entries_reversed(self):
        """Entries fully reversed by a posted credit note / reversal entry: same as cancelled for
        the construction documents (owner and subcontractor invoices, financial operations of the
        project).
        """

        def fully_reversed(move):
            """Fully reversed."""
            if move.state != 'posted':
                return False
            if move.payment_state == 'reversed':
                return True
            reversals = move.reversal_move_ids.filtered(lambda r: r.state == 'posted')
            return (
                move.move_type == 'entry'
                and bool(reversals)
                and move.currency_id.compare_amounts(
                    sum(reversals.mapped('amount_total')), move.amount_total
                )
                >= 0
            )

        reversed_moves = self.sudo().filtered(fully_reversed)
        if not reversed_moves:
            return
        model_attribute(reversed_moves, '_construction_documents_cancelled')()
        operations = (
            self.env['construction.project.operation']
            .sudo()
            .search([('move_id', 'in', reversed_moves.ids), ('state', '=', 'posted')])
        )
        for operation in operations:
            operation.write({'state': 'cancelled'})
            operation.message_post(
                body=_('The journal entry was reversed: the operation is cancelled.')
            )

    def _reverse_moves(self, default_values_list=None, cancel=False):
        reversals = super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)
        self._construction_entries_reversed()
        return reversals

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        reversals = posted.filtered('reversed_entry_id')
        if reversals:
            model_attribute(reversals.reversed_entry_id, '_construction_entries_reversed')()
        return posted

    def unlink(self):
        """Unlink."""
        moves = self.filtered(
            lambda m: m.construction_owner_invoice_id or m.construction_subcontract_invoice_id
        )
        model_attribute(moves, '_construction_documents_cancelled')()
        return super().unlink()
