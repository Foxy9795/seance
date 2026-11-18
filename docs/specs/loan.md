# Spec: LOAN (from `legacy/loan/loan.cbl`)

Purpose, from the source comment: Monthly payment for a fixed-rate loan. A result that does not fit, or a division by zero, gives status E and zero amounts instead of a bad number.

The program reads `INPUT.DAT` (text lines), writes `OUTPUT.DAT` (text lines). Source format: free.

## Input file INPUT.DAT: IN-REC (25 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| IN-LOAN-ID | 1-8 | text, 8 characters |
| IN-PRINCIPAL | 9-17 | number, 7 integer digit(s), 2 decimal(s), unsigned |
| IN-RATE | 18-22 | number, 1 integer digit(s), 4 decimal(s), unsigned |
| IN-TERM | 23-25 | number, 3 integer digit(s), 0 decimal(s), unsigned |

## Output file OUTPUT.DAT: OUT-REC (29 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| OUT-LOAN-ID | 1-8 | text, 8 characters |
| OUT-PAYMENT | 9-17 | number, 7 integer digit(s), 2 decimal(s), unsigned |
| OUT-INTEREST | 18-28 | number, 8 integer digit(s), 2 decimal(s), separate +/- character first |
| OUT-STATUS | 29-29 | text, 1 characters |

## Behavior by paragraph


### MAIN-PARA (line 21)

- L22: Opens files (input in-file output out-file).
- L23: Repeats the steps below until WS-EOF = "Y".
  - L24: Reads the next record from IN-FILE.
    - L25: When the file is exhausted: copies "Y" into WS-EOF.
    - L26: When there is another record: runs paragraph PROCESS-PARA.
- L29: Closes IN-FILE and OUT-FILE.
- L30: Ends the program.

### PROCESS-PARA (line 31)

- L32: Copies IN-LOAN-ID into OUT-LOAN-ID.
- L33: Copies "K" into OUT-STATUS.
- L34: Copies 0 into WS-PAY.
- L35: Calculates IN-RATE / 12 and stores it in WS-R, with extra decimals cut off (not rounded).
- L36: If IN-RATE = 0:
  - L37: Calculates IN-PRINCIPAL / IN-TERM and stores it in WS-PAY, rounded half away from zero.
    - L38: If that result does not fit or a division by zero happens, sets OUT-STATUS to "E".
- L40: Otherwise:
  - L41: Calculates IN-PRINCIPAL * WS-R / (1 - (1 + WS-R) ** (0 - IN-TERM)) and stores it in WS-PAY, rounded half away from zero.
    - L43: If that result does not fit or a division by zero happens, sets OUT-STATUS to "E".
- L46: If OUT-STATUS = "E":
  - L47: Copies 0 into OUT-PAYMENT.
  - L48: Copies 0 into OUT-INTEREST.
- L49: Otherwise:
  - L50: Copies WS-PAY into OUT-PAYMENT. (OUT-PAYMENT holds 9999999.99 at most; larger values lose their leading digits)
  - L51: Calculates WS-PAY * IN-TERM - IN-PRINCIPAL and stores it in OUT-INTEREST, with extra decimals cut off (not rounded).
- L53: Writes record OUT-REC to the output file.

## Where values can silently change

- L35: `WS-R` truncates extra decimals. A result that does not fit loses its leading digits (holds 9.9999999999 at most). A migration must reproduce this exactly.
- L37: `WS-PAY` rounds half away from zero. A result that does not fit triggers the ON SIZE ERROR branch instead of losing digits. A migration must reproduce this exactly.
- L41: `WS-PAY` rounds half away from zero. A result that does not fit triggers the ON SIZE ERROR branch instead of losing digits. A migration must reproduce this exactly.
- L51: `OUT-INTEREST` truncates extra decimals. A result that does not fit loses its leading digits (holds +/-99999999.99 at most). A migration must reproduce this exactly.

## Needs human review

- Every statement was recognized.
