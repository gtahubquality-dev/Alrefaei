import { patch } from "@web/core/utils/patch";
import { SaleOrderLineListRenderer } from "@sale/js/sale_order_line_field/sale_order_line_field";

patch(SaleOrderLineListRenderer.prototype, {
    onCellKeydownEditMode(hotkey, cell, group, record) {
        if (hotkey === "enter") {
            return super.onCellKeydownEditMode("tab", cell, group, record);
        }
        return super.onCellKeydownEditMode(...arguments);
    },
});
