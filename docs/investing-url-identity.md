# Investing.com Instrument Identity Contract

Last audited: 2026-08-08

## Observed URL model

Investing.com does not derive instrument URLs directly from a US ticker. The second path
segment is an opaque, often historical slug:

- US stocks and ADRs: `https://www.investing.com/equities/<legacy-slug>`
- US ETFs and ETNs: `https://www.investing.com/etfs/<legacy-slug>`

Examples verified through Investing.com's live search and instrument pages:

- `AAPL` -> `/equities/apple-computer-inc`
- `QQQ` -> `/etfs/powershares-qqqq`
- `SPY` -> `/etfs/spdr-s-p-500`
- `ABBNY` -> `/equities/abb-ltd-adr`
- `BRK.B` -> `/equities/berkshire-hathaway`, displayed by Investing as `BRKb`

The slug must never be guessed from the company name or ticker.

## Search-result identity

The live search result label supplies four identity fields:

`<symbol> <instrument name> <Stock|Equity|ETF> - <exchange> <equities|etf>`

The same symbol can occur for unrelated securities and on multiple exchanges. For example,
`QQQ` returns both Invesco QQQ Trust (`ETF - NASDAQ`) and Questcorp Mining
(`Stock - CBOE Canada`). Result order is not an identity guarantee.

Alternate exchange listings can share the same path and use a numeric `cid` query parameter.
The queryless page is often the US primary listing, but selection must be based on the displayed
exchange, symbol, and instrument type. When a verified mapping includes `?cid=<number>`, the
parameter must be preserved on every derived page.

## Application acceptance rules

A mapping is usable only when all of these checks pass:

1. The result symbol exactly identifies the requested ticker. Dot/hyphen share-class notation
   may match Investing's compact suffix form, such as `BRK.B`, `BRK-B`, and `BRKb`.
2. The displayed exchange is in the explicit US allowlist.
3. Polygon's security type agrees with the URL family and Investing result type.
4. The canonical URL is HTTPS on `www.investing.com`, contains exactly one instrument root,
   and has no query other than one numeric `cid`.
5. The mapping was produced under `us_instrument_identity_v3` with high confidence.
6. After navigation, the final URL must equal the requested instrument route, including `cid`.

Company-name similarity is a ranking and diagnostic signal only. It cannot authorize a different
ticker, ADR, ordinary share, or exchange listing.

## Derived routes

For equities, supported research tabs are formed by adding the suffix before any `cid` query:

- `-financial-summary`
- `-ratios`
- `-cash-flow`
- `-consensus-estimates`
- `-ownership`
- `-news`
- `-opinion`
- `-options`

ETFs use only the verified overview, news, opinion, and options routes. Stock-only financial,
forecast, ratio, and ownership routes must not be generated for ETFs.

## Regression matrix

- Normal US stock: `AAPL`
- ETF with same-symbol stock collision: `QQQ`
- ETF with international duplicates: `SPY`
- Exact OTC ADR versus different exchange ticker: `ABBNY`
- Punctuated share class: `BRK.B`
- Redirect to another slug: must fail
- Non-US-only exact symbol: must remain unmapped
- Cached mapping from an older policy: must be rediscovered before use

