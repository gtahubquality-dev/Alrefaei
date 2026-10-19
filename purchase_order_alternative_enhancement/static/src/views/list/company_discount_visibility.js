import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

const MODELS = new Set([
    "purchase.order", "purchase.order.line", "purchase.requisition",
    "purchase.requisition.line", "product.supplierinfo",
]);
const CUSTOM_FIELDS = new Set(["weighted_discount", "vendor_last_discount", "reorder_min_qty"]);
const OPTIONAL_COMPARE_FIELDS = new Set([
    "order_id", "state", "name", "date_planned", "product_qty",
    "product_uom_id", "price_unit", "price_subtotal", "price_total_cc",
]);

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        if (!MODELS.has(this.props.list.resModel)) {
            return;
        }
        const orm = useService("orm");
        onWillStart(async () => {
            const [company] = await orm.read(
                "res.company", [user.activeCompany.id], ["enable_free_customizations"]
            );
            this.purchaseCustomizationsEnabled = company.enable_free_customizations;
        });
    },

    processAllColumn(allColumns, list) {
        const columns = super.processAllColumn(...arguments);
        if (!MODELS.has(list.resModel)) {
            return columns;
        }
        const parent = list.evalContext.parent;
        const enabled = this.purchaseCustomizationsEnabled && (
            parent?.free_customizations_enabled ?? (
                list.records.length
                    ? list.records.some((record) => record.data.free_customizations_enabled)
                    : true
            )
        );
        // Filter before optional-field preferences and menus are built, so a
        // saved preference cannot expose these columns for disabled companies.
        if (!enabled) {
            return columns.filter((column) => !CUSTOM_FIELDS.has(column.name));
        }
        if (
            list.resModel === "purchase.order.line" &&
            columns.some((column) => column.name === "price_total_cc")
        ) {
            return columns.map((column) => OPTIONAL_COMPARE_FIELDS.has(column.name)
                ? { ...column, optional: "show" }
                : column);
        }
        return columns;
    },
});
