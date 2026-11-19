"""Construction equipment construction dashboard mixin support."""

from markupsafe import Markup
from odoo import _, models
from odoo.tools.misc import formatLang


class ConstructionDashboardMixin(models.AbstractModel):
    """HTML rendering helpers shared by the equipment and fleet dashboards (escaped values only)."""

    _name = 'construction.dashboard.mixin'
    _description = 'Construction Dashboard Helpers'

    def _money(self, amount):
        return formatLang(self.env, amount, currency_obj=self.currency_id)

    @staticmethod
    def _num(value, digits=1):
        return f'{value:,.{digits}f}'

    def _html_empty(self, message):
        return Markup('<div class="text-muted fst-italic py-3 text-center">%s</div>') % message

    def _html_table(self, headers, rows, numeric_from=1, footer=None):
        head = Markup('').join(
            (
                Markup('<th class="%s">%s</th>')
                % ('text-end' if index >= numeric_from else '', header)
                for (index, header) in enumerate(headers)
            )
        )
        body = Markup('')
        for row in rows:
            cells = Markup('').join(
                (
                    Markup('<td class="%s">%s</td>')
                    % ('text-end text-nowrap' if index >= numeric_from else '', cell)
                    for (index, cell) in enumerate(row)
                )
            )
            body += Markup('<tr>%s</tr>') % cells
        foot = Markup('')
        if footer:
            foot = Markup('<tfoot><tr class="fw-bold">%s</tr></tfoot>') % Markup('').join(
                (
                    Markup('<td class="%s">%s</td>')
                    % ('text-end text-nowrap' if index >= numeric_from else '', cell)
                    for (index, cell) in enumerate(footer)
                )
            )
        return self._html_table_shell(head, body, foot)

    def _render_cost_bar(self, items):
        """Render cost labels, amounts, and CSS colors as a stacked bar with a legend."""
        total = sum((amount for (_label, amount, _css) in items))
        if not total:
            return self._html_empty(_('No cost recorded in this period.'))
        progress_bar = Markup('')
        legend = Markup('')
        for label, amount, css in items:
            share = amount / total * 100.0
            if amount:
                progress_bar += Markup(
                    (
                        '<div class="progress-bar %s" role="progressbar" '
                        'style="width: %s%%" title="%s"></div>'
                    )
                ) % (css, f'{share:.2f}', label)
            legend += Markup(
                (
                    '<div class="d-flex justify-content-between '
                    'align-items-center py-1 border-bottom"><span><span '
                    'class="d-inline-block rounded-circle me-2 %s" '
                    'style="width:10px;height:10px"></span>%s</span><span '
                    'class="text-nowrap d-inline-flex gap-2 '
                    'align-items-baseline"><span '
                    'class="fw-semibold">%s</span><span '
                    'class="text-muted small">%s%%</span></span></div>'
                )
            ) % (css, label, self._money(amount), f'{share:.0f}')
        return Markup('<div class="progress mb-3" style="height: 14px">%s</div>%s') % (
            progress_bar,
            legend,
        )

    def _render_alert_list(self, items):
        """items: [(text css class, font awesome icon, text)]"""
        if not items:
            return Markup(
                (
                    '<div class="text-success py-3 text-center"><i '
                    'class="fa fa-check-circle me-1"></i>%s</div>'
                )
            ) % _('Nothing to report.')
        return Markup('<ul class="list-unstyled mb-0">%s</ul>') % Markup('').join(
            (
                Markup(('<li class="py-1 border-bottom"><i class="fa %s %s me-2"></i>%s</li>'))
                % (icon, css, text)
                for (css, icon, text) in items
            )
        )

    def _html_table_shell(self, head, body, foot):
        """Wrap pre-rendered table sections in the shared responsive markup."""
        return Markup(
            (
                '<div class="table-responsive"><table class="table '
                'table-sm table-hover align-middle mb-0"><thead '
                'class="table-light"><tr>%s</tr></thead><tbody>%s</tbody>%s</table></div>'
            )
        ) % (head, body, foot)
