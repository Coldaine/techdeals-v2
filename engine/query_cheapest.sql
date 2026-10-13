-- Cheapest current offer of one named spec, with source, URL, and time.
-- Single-member (or line-priced) offers only: a server bundle that merely
-- contains a 32GB DIMM must not answer "cheapest 32GB DIMM".
-- Unresolved rows stay in the result (product_key may be null).

\pset pager off

SELECT '32GB DDR4 RDIMM' AS spec,
       unit_price, price_basis, amount, amount_covers_units,
       label, source, url, fetched_at,
       product_key, availability_state
FROM v_cheapest_available
WHERE availability_state = 'available'
  AND price_basis = 'explicit_unit'
  AND (member_line_count IS NULL OR member_line_count = 1)
  AND attributes @> '{"ram_dimm_gb": 32}'::jsonb
  AND COALESCE(attributes->>'ram_type', '') ILIKE '%DDR4%'
ORDER BY unit_price NULLS LAST
LIMIT 5;

SELECT '1000GB SSD' AS spec,
       unit_price, price_basis, amount, amount_covers_units,
       label, source, url, fetched_at,
       product_key, availability_state
FROM v_cheapest_available
WHERE availability_state = 'available'
  AND price_basis IN ('explicit_unit', 'homogeneous_division')
  AND (member_line_count IS NULL OR member_line_count = 1)
  AND lower(attributes->>'storage_kind') = 'ssd'
  AND (
        attributes @> '{"storage_capacity_gb": 1000}'::jsonb
     OR attributes @> '{"storage_capacity_gb": 1024}'::jsonb
  )
ORDER BY unit_price NULLS LAST
LIMIT 5;
