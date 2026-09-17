import { patch } from "@web/core/utils/patch";
import { PurchaseOrderLineCompareListRenderer } from "@purchase_requisition/views/list/purchase_order_line_compare_list_renderer";

patch(PurchaseOrderLineCompareListRenderer.prototype, {
    setup() {
        super.setup();
        this.bestFields.best_weighted_discount_ids = [];
        this.bestFields.low_stock_line_ids = [];
    },

    async updateBestFields() {
        await super.updateBestFields();
        const purchaseOrderId = this.props.list.context.purchase_order_id || this.props.list.context.active_id;
        [
            this.bestFields.best_weighted_discount_ids,
            this.bestFields.low_stock_line_ids,
        ] = await Promise.all([
            this.props.list.model.orm.call(
                "purchase.order",
                "get_tender_best_weighted_discount_lines",
                [purchaseOrderId],
                { context: this.props.list.context }
            ),
            this.props.list.model.orm.call(
                "purchase.order",
                "get_tender_low_stock_lines",
                [purchaseOrderId],
                { context: this.props.list.context }
            ),
        ]);
    },

    getCellClass(column, record) {
        let classNames = super.getCellClass(...arguments);
        if (
            column.name === "weighted_discount" &&
            this.bestFields.best_weighted_discount_ids.includes(record.resId)
        ) {
            classNames += " text-success";
        }
        if (
            column.name === "reorder_min_qty" &&
            this.bestFields.low_stock_line_ids.includes(record.resId)
        ) {
            classNames += " text-danger";
        }
        return classNames;
    },
});
