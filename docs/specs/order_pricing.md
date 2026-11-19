# Spec: ORDER_PRICING (from `legacy/order_pricing/order_pricing.cbl`)

Purpose, from the source comment: Prices orders by calling a pricing module and a counter module.

The program reads `ORDERIN` (text lines), writes `PRICEOUT` (text lines). Source format: fixed (columns 8-72).

Note: It CALLs NOSUCHPG, which is not in this program's folder. Add NOSUCHPG's source to run that CALL.

## Input file ORDERIN: ORDER-REC (15 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| O-ID | 1-5 | text, 5 characters |
| O-QTY | 6-8 | number, 3 integer digit(s), 0 decimal(s), unsigned |
| O-PRICE | 9-14 | number, 4 integer digit(s), 2 decimal(s), unsigned |
| O-CODE | 15-15 | text, 1 characters |

## Output file PRICEOUT: PRICED-REC (23 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| P-ID | 1-5 | text, 5 characters |
| FILLER | 6-6 | text, 1 characters |
| P-TOTAL | 7-16 | number shown with editing, picture `ZZZZZZ9.99` |
| FILLER | 17-17 | text, 1 characters |
| P-RC | 18-18 | number, 1 integer digit(s), 0 decimal(s), unsigned |
| FILLER | 19-19 | text, 1 characters |
| P-SEEN | 20-23 | number, 4 integer digit(s), 0 decimal(s), unsigned |

## Behavior by paragraph


### MAIN-PARA (line 39)

- L40: Opens files (input orders output priced).
- L41: Repeats the steps below until WS-EOF = 'Y'.
  - L42: Reads the next record from ORDERS.
    - L43: When the file is exhausted: copies 'Y' into WS-EOF.
    - L44: When there is another record: runs paragraph PRICE-ONE.
- L47: (not summarized) `CALL 'NOSUCHPG' USING WS-ARGS`
  - L48: (not summarized) `ON EXCEPTION MOVE 'Y' TO WS-MISSING`
- L49: (not summarized) `END-CALL`
- L50: Shows 'MISSING MODULE HANDLED: ' WS-MISSING on the console.
- L51: (not summarized) `CANCEL 'COUNTER'`
- L52: (not summarized) `CALL 'COUNTER' USING WS-SEEN WS-BLANK`
- L53: Shows 'AFTER CANCEL: ' WS-SEEN on the console.
- L54: Closes ORDERS and PRICED.
- L55: Ends the program.

### PRICE-ONE (line 56)

- L57: Copies O-QTY into WS-QTY. (WS-QTY holds 999 at most; larger values lose their leading digits)
- L58: Copies O-PRICE into WS-PRICE. (WS-PRICE holds 9999.99 at most; larger values lose their leading digits)
- L59: Copies O-CODE into WS-CODE.
- L60: (not summarized) `CALL 'PRICER' USING BY REFERENCE WS-ARGS`
- L61: Copies RETURN-CODE into P-RC. (P-RC holds 9 at most; larger values lose their leading digits)
- L62: (not summarized) `CALL 'COUNTER' USING BY REFERENCE WS-SEEN`
          - L63: (not summarized) `BY CONTENT O-ID`
- L64: Copies O-ID into P-ID.
- L65: Copies WS-TOTAL into P-TOTAL.
- L66: Copies WS-SEEN into P-SEEN. (P-SEEN holds 9999 at most; larger values lose their leading digits)
- L67: Writes record PRICED-REC to the output file.

## Where values can silently change

- None detected.

## Needs human review

- line 47: `CALL 'NOSUCHPG' USING WS-ARGS` was not summarized
- line 48: `ON EXCEPTION MOVE 'Y' TO WS-MISSING` was not summarized
- line 49: `END-CALL` was not summarized
- line 51: `CANCEL 'COUNTER'` was not summarized
- line 52: `CALL 'COUNTER' USING WS-SEEN WS-BLANK` was not summarized
- line 60: `CALL 'PRICER' USING BY REFERENCE WS-ARGS` was not summarized
- line 62: `CALL 'COUNTER' USING BY REFERENCE WS-SEEN` was not summarized
- line 63: `BY CONTENT O-ID` was not summarized
