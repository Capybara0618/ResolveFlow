-- C12-display: two presentational columns on the order line, added only.
--
-- docs: tasks/dsh-reviewer/05-fields-visual.md section 2. A reviewer looking at an order line
-- sees a SKU such as `SKU-RED-M-DEMO-90929041801`, which says nothing about what was bought; the
-- reviewer page needs a product name and, when there is one, the variant the customer chose.
--
-- Shape, and why it is this shape:
--   * both columns are NULLable with no default, so every existing row keeps saying "not
--     provided" rather than being backfilled with an invented name. A display field that guessed
--     would be worse than a blank one.
--   * VARCHAR(200) matches the contract's maxLength: a longer value is refused at the boundary
--     rather than silently truncated, because half a product name is a different product name.
--   * they are *presentation*. They are not read by `findContext`, so they do not enter the
--     refund re-check's LineContext, the tool evidence hash or any amount computation: what a
--     reviewer reads and what the money path recomputes stay separate.
--
-- Appending a migration is the only way to change a schema here (docs/engineering.md:64): this
-- file is never edited once applied, and V1..V6 are untouched.
ALTER TABLE order_line
    ADD COLUMN product_name VARCHAR(200) NULL AFTER sku,
    ADD COLUMN variant_text VARCHAR(200) NULL AFTER product_name;
