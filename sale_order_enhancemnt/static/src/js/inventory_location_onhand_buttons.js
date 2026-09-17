import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class InventoryLocationOnhandButtons extends Component {
    static template = "sale_order_enhancemnt.InventoryLocationOnhandButtons";
    static props = { ...standardFieldProps };

    setup() {
        this.action = useService("action");
    }

    get buttons() {
        return this.props.record.data[this.props.name] || [];
    }

    openLocation(button) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: button.location_name,
            res_model: "stock.quant",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["product_id", "=", button.product_id],
                ["location_id", "=", button.location_id],
                ["quantity", ">", 0],
            ],
            context: {
                search_default_internal_loc: 1,
                default_product_id: button.product_id,
                default_location_id: button.location_id,
            },
        });
    }
}

registry.category("fields").add("inventory_location_onhand_buttons", {
    component: InventoryLocationOnhandButtons,
});
