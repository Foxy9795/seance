# Spec: ACCOUNTS (from `legacy/accounts/accounts.cbl`)

Purpose, from the source comment: Month-end account maintenance: compound interest on savings, a tiered service fee on checking, and an overdraft check.

Reads `ACCTIN` (fixed-length records) and writes `ACCTOUT` (fixed-length records). Source format: fixed (columns 8-72).

## Input record (38 characters per record)

| Field | Columns | Meaning of the picture |
| --- | --- | --- |
| ACCT-NO | 1-8 | text, 8 characters |
| ACCT-BALANCE | 9-17 | number, 7 integer digit(s), 2 decimal(s), sign stored in the last digit (a negative shows as p to y) |
| ACCT-LIMIT | 18-26 | number, 7 integer digit(s), 2 decimal(s), unsigned |
| ACCT-RATE | 27-30 | number, 0 integer digit(s), 4 decimal(s), unsigned |
| ACCT-TYPE | 31-31 | text, 1 characters |
| ACCT-MONTHS | 32-33 | number, 2 integer digit(s), 0 decimal(s), unsigned |
| FILLER | 34-38 | text, 5 characters |

## Output record (53 characters per record)

| Field | Columns | Meaning of the picture |
| --- | --- | --- |
| OUT-ACCT-NO | 1-8 | text, 8 characters |
| OUT-NEW-BAL | 9-17 | number, 7 integer digit(s), 2 decimal(s), sign stored in the last digit (a negative shows as p to y) |
| OUT-FEE | 18-22 | number, 3 integer digit(s), 2 decimal(s), unsigned |
| OUT-INTEREST | 23-29 | number, 5 integer digit(s), 2 decimal(s), unsigned |
| OUT-STATUS | 30-39 | text, 10 characters |
| OUT-SHOWN | 40-53 | number shown with editing, picture `$$,$$$,$$9.99-` |

## Behavior by paragraph


### 0000-MAIN (line 32)

- L33: Opens files (input  acct-in).
  - L34: (continued) opens ACCT-OUT for writing.
- L35: Runs paragraph 8000-READ.
- L36: Runs paragraph 1000-PROCESS again and again until END-OF-FILE.
- L37: Closes ACCT-IN and ACCT-OUT.
- L38: Ends the program.

### 1000-PROCESS (line 39)

- L40: Resets OUT-REC: numbers to zero, text to spaces.
- L41: Copies ACCT-NO      into OUT-ACCT-NO.
- L42: Copies ACCT-BALANCE into WS-BAL. (WS-BAL holds +/-999999999.9999 at most; larger values lose their leading digits)
- L43: Adds 1 to WS-COUNT.
- L44: Picks the first case below that is true:
  - L45: Case: SAVINGS.
    - L46: Runs paragraph 2000-INTEREST.
  - L47: Case: CHECKING.
    - L48: Runs paragraph 3000-FEE.
  - L49: In every other case:
    - L50: Copies 'UNKNOWN' into OUT-STATUS.
- L52: If WS-BAL < ZERO:
  - L53: If 0 - WS-BAL > ACCT-LIMIT:
    - L54: Copies 'OVER-LIMIT' into OUT-STATUS.
  - L55: Otherwise:
    - L56: Copies 'OVERDRAWN' into OUT-STATUS.
- L58: Otherwise:
  - L59: If OUT-STATUS = SPACES:
    - L60: Copies 'OK' into OUT-STATUS.
- L63: Calculates WS-BAL and stores it in OUT-NEW-BAL, with extra decimals cut off (not rounded).
- L64: Copies OUT-NEW-BAL into OUT-SHOWN.
- L65: Writes record OUT-REC to the output file.
- L66: Runs paragraph 8000-READ.

### 2000-INTEREST (line 67)

- L68: Calculates ACCT-RATE / 12 and stores it in WS-MONTH-RATE, with extra decimals cut off (not rounded).
- L69: Repeats the steps below with WS-I counting from 1 in steps of 1, until WS-I > ACCT-MONTHS.
  - L70: Calculates WS-BAL * (1 + WS-MONTH-RATE) and stores it in WS-BAL, rounded half away from zero.
- L72: Calculates WS-BAL - ACCT-BALANCE and stores it in OUT-INTEREST, rounded half away from zero.
  - L73: If that result does not fit or a division by zero happens, sets OUT-INTEREST to 99999.99.

### 3000-FEE (line 75)

- L76: Picks the first case below that is true:
  - L77: Case: WS-BAL >= 2500.
    - L78: Copies 0 into OUT-FEE.
  - L79: Case: WS-BAL >= 500.
    - L80: Copies 4.50 into OUT-FEE.
  - L81: In every other case:
    - L82: Copies 12.00 into OUT-FEE.
- L84: Subtracts OUT-FEE from WS-BAL.

### 8000-READ (line 85)

- L86: Reads the next record from ACCT-IN.
  - L87: When the file is exhausted: makes condition END-OF-FILE true.

## Where values can silently change

- L63: `OUT-NEW-BAL` truncates extra decimals. A result that does not fit loses its leading digits (holds +/-9999999.99 at most). A migration must reproduce this exactly.
- L68: `WS-MONTH-RATE` truncates extra decimals. A result that does not fit loses its leading digits (holds 9.999999 at most). A migration must reproduce this exactly.
- L70: `WS-BAL` rounds half away from zero. A result that does not fit loses its leading digits (holds +/-999999999.9999 at most). A migration must reproduce this exactly.
- L72: `OUT-INTEREST` rounds half away from zero. A result that does not fit triggers the ON SIZE ERROR branch instead of losing digits. A migration must reproduce this exactly.

## Needs human review

- Every statement was recognized.
