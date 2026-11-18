# SEC EDGAR data notes

## Endpoints
- Ticker -> CIK: `https://www.sec.gov/files/company_tickers.json` (pad CIK to 10 digits).
- All reported facts: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
- Headers: `User-Agent: <name> <email>` is required or you get 403. Max ~10 requests/second.

## Shape of companyfacts
`facts -> us-gaap -> <Tag> -> units -> USD -> [ {start, end, val, fy, fp, form, filed, frame, accn}, ... ]`
- Flow items (revenue, expenses, cash flows) have `start` and `end`. Balance sheet items are instants (only `end`).
- Shares use unit `shares`; EPS uses `USD/shares`.

## Gotchas to handle
1. **Duplicates.** The same period's value appears in many filings (restated, repeated as comparatives). Dedupe by (start, end), keeping the value from the earliest filing for backtests (what was known then) or the latest filing for "current view". Make this a parameter.
2. **YTD vs quarterly.** 10-Q flow items are often reported both as 3-month and year-to-date. Keep periods whose duration is ~80-100 days for quarters, ~350-380 days for annual.
3. **Q4 is not filed as a quarter.** Derive Q4 = FY value minus Q1+Q2+Q3 for flow items. Balance sheet Q4 = FY-end instant.
4. **Tag drift.** Companies switch tags over time (e.g. `SalesRevenueNet` -> `RevenueFromContractWithCustomerExcludingAssessedTax` after ASC 606 in 2018). For each period, take the first tag in the candidate list that has a value for that period, not the first tag that exists at all.
5. **Fiscal years.** `fy`/`fp` refer to the filing, not the period. Use `start`/`end` dates to assign periods. Label by the company's fiscal calendar.
6. **Sign conventions.** Capex (`PaymentsToAcquirePropertyPlantAndEquipment`) is reported positive; show as outflow in the cash flow view.
7. **Derived items.** If GrossProfit is missing, compute Revenue - COGS and mark it "derived". Same for Operating Income if components exist.
8. **The `filed` date** is the key for no-look-ahead backtests.
