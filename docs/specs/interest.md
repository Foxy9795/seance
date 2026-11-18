# Spec: INTEREST (from `legacy/interest/interest.cbl`)

Purpose, from the source comment: Nightly interest posting. Overdrawn accounts earn nothing and pay a fee.

The program reads `INPUT.DAT` (text lines), writes `OUTPUT.DAT` (text lines). Source format: free.

## Input file INPUT.DAT: IN-REC (28 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| IN-ACCT-ID | 1-8 | text, 8 characters |
| IN-BALANCE | 9-20 | number, 9 integer digit(s), 2 decimal(s), separate +/- character first |
| IN-RATE | 21-25 | number, 1 integer digit(s), 4 decimal(s), unsigned |
| IN-DAYS | 26-28 | number, 3 integer digit(s), 0 decimal(s), unsigned |

## Output file OUTPUT.DAT: OUT-REC (33 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| OUT-ACCT-ID | 1-8 | text, 8 characters |
| OUT-INTEREST | 9-20 | number, 9 integer digit(s), 2 decimal(s), separate +/- character first |
| OUT-NEW-BAL | 21-32 | number, 9 integer digit(s), 2 decimal(s), separate +/- character first |
| OUT-STATUS | 33-33 | text, 1 characters |

## Behavior by paragraph


### MAIN-PARA (line 19)

- L20: Opens files (input in-file output out-file).
- L21: Repeats the steps below until WS-EOF = "Y".
  - L22: Reads the next record from IN-FILE.
    - L23: When the file is exhausted: copies "Y" into WS-EOF.
    - L24: When there is another record: runs paragraph PROCESS-PARA.
- L27: Closes IN-FILE and OUT-FILE.
- L28: Ends the program.

### PROCESS-PARA (line 29)

- L30: Copies IN-ACCT-ID into OUT-ACCT-ID.
- L31: Picks the first case below that is true:
  - L32: Case: IN-BALANCE > 0.
    - L33: Copies "P" into OUT-STATUS.
    - L34: Calculates IN-BALANCE * IN-RATE * IN-DAYS / 365 and stores it in WS-INT, rounded half away from zero.
    - L35: Calculates IN-BALANCE + WS-INT and stores it in OUT-NEW-BAL, with extra decimals cut off (not rounded).
  - L36: Case: IN-BALANCE < 0.
    - L37: Copies "O" into OUT-STATUS.
    - L38: Copies 0 into WS-INT.
    - L39: Calculates IN-BALANCE - 25.00 and stores it in OUT-NEW-BAL, with extra decimals cut off (not rounded).
  - L40: In every other case:
    - L41: Copies "Z" into OUT-STATUS.
    - L42: Copies 0 into WS-INT.
    - L43: Copies 0 into OUT-NEW-BAL.
- L45: Copies WS-INT into OUT-INTEREST. (OUT-INTEREST holds +/-999999999.99 at most; larger values lose their leading digits)
- L46: Writes record OUT-REC to the output file.

## Where values can silently change

- L34: `WS-INT` rounds half away from zero. A result that does not fit loses its leading digits (holds +/-999999999.99 at most). A migration must reproduce this exactly.
- L35: `OUT-NEW-BAL` truncates extra decimals. A result that does not fit loses its leading digits (holds +/-999999999.99 at most). A migration must reproduce this exactly.
- L39: `OUT-NEW-BAL` truncates extra decimals. A result that does not fit loses its leading digits (holds +/-999999999.99 at most). A migration must reproduce this exactly.

## Needs human review

- Every statement was recognized.
