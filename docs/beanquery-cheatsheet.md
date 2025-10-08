# BeanQuery Cheat Sheet

This server uses BeanQuery (beanquery) to answer read-only questions on your Beancount v3 ledger. Queries are SQL‑like and operate over entries, accounts, dates, and positions.

- Dates: Use `date('YYYY-MM-DD')` in comparisons.
- Aggregation: `sum(position)` returns an inventory; results are numberified on the server when appropriate.
- Grouping: Use `GROUP BY` to aggregate by account, payee, month, etc.

## Common Patterns

- Balance by account prefix (Assets):
  SELECT account, sum(position)
  WHERE account ~ '^Assets'
  GROUP BY account
  ORDER BY account

- Expenses total over a month:
  SELECT sum(position)
  WHERE account ~ '^Expenses'
    AND date >= date('2020-01-01')
    AND date <= date('2020-01-31')

- Expenses by category with totals:
  SELECT account, sum(position)
  WHERE account ~ '^Expenses'
  GROUP BY account
  ORDER BY sum(position) DESC

- Income by payee:
  SELECT payee, sum(position)
  WHERE account ~ '^Income'
  GROUP BY payee
  ORDER BY sum(position)

- Net Income for a period (Income + Expenses):
  SELECT sum(position)
  WHERE (account ~ '^Income' OR account ~ '^Expenses')
    AND date >= date('2020-01-01') AND date <= date('2020-12-31')

- Filter by narration substring:
  SELECT *
  WHERE narration ~ 'rent'

- Filter by tag (tag matching depends on how tags are exposed in your entries):
  SELECT *
  WHERE tags ? 'reimbursable'

Notes:
- The exact set of functions/operators supported comes from the `beanquery` package. Date literals MUST be wrapped in `date('...')` for comparisons.
- `sum(position)` without explicit conversion leaves native currencies; the server may numberify values for convenience in responses.
