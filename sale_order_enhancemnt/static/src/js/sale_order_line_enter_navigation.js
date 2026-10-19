import { useExternalListener } from "@odoo/owl";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { getActiveHotkey } from "@web/core/hotkeys/hotkey_service";
import { patch } from "@web/core/utils/patch";
import { SaleOrderLineListRenderer } from "@sale/js/sale_order_line_field/sale_order_line_field";

const PRODUCT_ENTER = "sale-order-line-product-enter";
const PRODUCT_FIELDS = ["product_id", "product_template_id"];
const AVAILABILITY_WIDGET = ".o_widget_qty_at_date_widget";

patch(AutoComplete.prototype, {
    async onInputKeydown(ev) {
        const cell = ev.target.closest("td[name='product_id'], td[name='product_template_id']");
        const isSaleProduct = cell?.closest(".o_field_widget[name='order_line']") &&
            cell.parentElement.querySelector("td[name='product_uom_qty']");
        if (getActiveHotkey(ev) !== "enter" || ev.isComposing || !isSaleProduct) {
            return super.onInputKeydown(...arguments);
        }

        // Keep normal suggestion selection, but do not let the product widget
        // consume Enter to open its description editor.
        ev.preventDefault();
        ev.stopPropagation();
        await super.onInputKeydown(...arguments);
        cell.dispatchEvent(new CustomEvent(PRODUCT_ENTER, { bubbles: true }));
    },
});

patch(SaleOrderLineListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        useExternalListener(window, PRODUCT_ENTER, (ev) => {
            if (this.tableRef.el?.contains(ev.target)) {
                this.focusQuantityAfterProduct(this.editedRecord);
            }
        });
        // Widget cells have no onCellKeydown binding in the list template.
        // Also handle Enter if the icon was focused by Tab or a mouse click.
        useExternalListener(window, "keydown", (ev) => {
            if (
                getActiveHotkey(ev) === "enter" &&
                !ev.isComposing &&
                this.editedRecord &&
                this.tableRef.el?.contains(ev.target) &&
                ev.target.closest(AVAILABILITY_WIDGET)
            ) {
                this.onCellKeydown(ev, null, this.editedRecord);
            }
        });
    },

    findNextFocusableOnRow(row, cell) {
        let toFocus = super.findNextFocusableOnRow(...arguments);
        while (this.skipAvailabilityOnEnter && toFocus?.closest(AVAILABILITY_WIDGET)) {
            const widgetCell = toFocus.closest("td");
            toFocus = super.findNextFocusableOnRow(row, widgetCell);
        }
        return toFocus;
    },

    async focusQuantityAfterProduct(record) {
        if (!record) {
            return;
        }
        // Product selection queues an onchange. Wait for it and the resulting
        // render before moving focus, so it cannot restore focus to Product.
        await record.model.mutex.exec(() => {});
        await new Promise((resolve) => requestAnimationFrame(resolve));
        if (
            this.editedRecord !== record ||
            !this.tableRef.el?.isConnected ||
            !record.data.product_id ||
            record.data.display_type ||
            document.activeElement?.closest(".o_dialog")
        ) {
            return;
        }
        const column = this.columns.find((column) => column.name === "product_uom_qty");
        if (column && !this.isCellReadonly(column, record)) {
            this.focusCell(column);
        }
    },

    onCellKeydownEditMode(hotkey, cell, group, record) {
        if (hotkey === "enter") {
            if (PRODUCT_FIELDS.includes(cell.getAttribute("name"))) {
                this.focusQuantityAfterProduct(record);
                return true;
            }
            this.skipAvailabilityOnEnter = true;
            try {
                return super.onCellKeydownEditMode("tab", cell, group, record);
            } finally {
                this.skipAvailabilityOnEnter = false;
            }
        }
        return super.onCellKeydownEditMode(...arguments);
    },
});
