# Customer Profile Preference Backfill Design

## Goal

Populate only empty `fin_customer_profile.asset_allocation` and
`fin_customer_profile.product_preference` values with auditable, risk-aligned
recommendation data derived from the real `fin_product` catalogue.

## Scope and Safety

- Target only rows whose corresponding JSON field is `NULL`, `{}`, or an empty
  string. Existing preference data is never overwritten.
- Do not modify customer risk code/name, risk score, holdings, transaction
  history, or any row in `fin_risk_assessment`.
- Select only products with `status = '在售'`; a candidate must not exceed the
  customer's risk code (`C1` to `C5` maps to `R1` to `R5`).

## Allocation Templates

The stored JSON uses `cash`, `bond`, `hybrid`, and `equity`, expressed as
decimal proportions and summing exactly to `1.00`.

| Risk code | Cash | Bond | Hybrid | Equity |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.30 | 0.55 | 0.15 | 0.00 |
| C2 | 0.20 | 0.45 | 0.25 | 0.10 |
| C3 | 0.15 | 0.35 | 0.30 | 0.20 |
| C4 | 0.10 | 0.20 | 0.35 | 0.35 |
| C5 | 0.05 | 0.10 | 0.25 | 0.60 |

## Product Preference Contract

`product_preference` is a JSON object with the following fields:

- `risk_level_code`: the profile's canonical `C1`–`C5` code.
- `allowed_product_risk_levels`: allowed `R1`–`R5` product risk levels,
  capped by the customer risk code.
- `preferred_product_types`: ordered product categories consistent with the
  allocation template.
- `candidate_products`: up to three real, in-sale products. Each entry records
  `product_code`, `product_name`, `product_type`, and `risk_level`.
- `generated_at`: UTC ISO-8601 timestamp for traceability.

Candidates are chosen deterministically by lowest risk first and then product
code, so re-running the operation produces stable results when the catalogue
is unchanged.

## Data Flow and Validation

1. Read all profile rows requiring either field and read the in-sale product
   catalogue.
2. Validate each profile risk code with `normalize_risk_level`; reject and
   report invalid rows rather than guessing.
3. Build allocation JSON and product-preference JSON independently for each
   missing field.
4. Update only the missing JSON columns in a transaction.
5. Verify every updated field is non-empty, each allocation sums to `1.00`,
   every candidate product exists and is in sale, and no candidate product's
   `R` level exceeds its customer's `C` level.

## Error Handling

The operation aborts before any write if the catalogue cannot supply a valid
candidate product for a profile's permitted risk range. It emits a concise
summary of updated rows and validation violations; a nonzero violation count
causes failure.

## Testing

Unit tests cover all C1–C5 templates, candidate-risk caps, deterministic
selection, empty-only update behaviour, and validation failures. A database
verification query checks the live update independently after execution.
