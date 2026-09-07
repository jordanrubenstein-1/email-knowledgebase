---
name: feedback_cz_product_inventory_check
description: Always run inventory_checker.py before recommending any product in a CZ, STF, or BUR brief — no exceptions
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 31791bb4-ac81-4c54-9984-71fa16ed3f73
---

Always run `inventory_checker.py --brand [CZ|STF|BUR] --search "[product name]"` before including any product in a CZ, STF, or BUR email brief. This is mandatory, not optional — even when the Asana task specifies a product explicitly.

**Why:** Product stock levels change; suggesting an out-of-stock or low-stock product in a brief wastes the designer's time and may go live with a dead or thin PDP.

**How to apply:** Before writing the Products section of any CZ, STF, or BUR Asana task (auto-brief or manual), run the inventory check for each product being considered. Do not suggest zero-stock or low-stock products. Use Snowflake via `inventory_checker.py` — not Looker. For ID and TI, inventory data is unavailable — note in the brief that stock hasn't been verified.
