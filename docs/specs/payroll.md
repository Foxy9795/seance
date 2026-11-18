# Spec: PAYROLL (from `legacy/payroll/payroll.cbl`)

Purpose, from the source comment: Weekly payroll: overtime at 1.5x past 40 hours, three tax brackets, flat benefits fee. Each money step is rounded when stored.

Reads `INPUT.DAT` (text lines) and writes `OUTPUT.DAT` (text lines). Source format: free.

## Input record (15 characters per record)

| Field | Columns | Meaning of the picture |
| --- | --- | --- |
| IN-EMP-ID | 1-6 | text, 6 characters |
| IN-HOURS | 7-10 | number, 3 integer digit(s), 1 decimal(s), unsigned |
| IN-RATE | 11-15 | number, 3 integer digit(s), 2 decimal(s), unsigned |

## Output record (31 characters per record)

| Field | Columns | Meaning of the picture |
| --- | --- | --- |
| OUT-EMP-ID | 1-6 | text, 6 characters |
| OUT-GROSS | 7-14 | number, 6 integer digit(s), 2 decimal(s), unsigned |
| OUT-TAX | 15-22 | number, 6 integer digit(s), 2 decimal(s), unsigned |
| OUT-NET | 23-31 | number, 6 integer digit(s), 2 decimal(s), separate +/- character first |

## Behavior by paragraph


### MAIN-PARA (line 23)

- L24: Opens files (input in-file output out-file).
- L25: Repeats the steps below until WS-EOF = "Y".
  - L26: Reads the next record from IN-FILE.
    - L27: When the file is exhausted: copies "Y" into WS-EOF.
    - L28: When there is another record: runs paragraph PROCESS-PARA.
- L31: Closes IN-FILE and OUT-FILE.
- L32: Ends the program.

### PROCESS-PARA (line 33)

- L34: Copies IN-EMP-ID into OUT-EMP-ID.
- L35: If IN-HOURS > 40:
  - L36: Calculates 40 * IN-RATE and stores it in WS-REG, rounded half away from zero.
  - L37: Calculates (IN-HOURS - 40) * IN-RATE * 1.5 and stores it in WS-OT, rounded half away from zero.
- L38: Otherwise:
  - L39: Calculates IN-HOURS * IN-RATE and stores it in WS-REG, rounded half away from zero.
  - L40: Copies 0 into WS-OT.
- L42: Calculates WS-REG + WS-OT and stores it in WS-GROSS, with extra decimals cut off (not rounded).
- L43: Picks the first case below that is true:
  - L44: Case: WS-GROSS <= 500.
    - L45: Calculates WS-GROSS * 0.10 and stores it in WS-TAX, rounded half away from zero.
  - L46: Case: WS-GROSS <= 1500.
    - L47: Calculates 50 + (WS-GROSS - 500) * 0.20 and stores it in WS-TAX, rounded half away from zero.
  - L48: In every other case:
    - L49: Calculates 250 + (WS-GROSS - 1500) * 0.30 and stores it in WS-TAX, rounded half away from zero.
- L51: Copies WS-GROSS into OUT-GROSS. (OUT-GROSS holds 999999.99 at most; larger values lose their leading digits)
- L52: Copies WS-TAX into OUT-TAX. (OUT-TAX holds 999999.99 at most; larger values lose their leading digits)
- L53: If IN-HOURS > 0:
  - L54: Calculates WS-GROSS - WS-TAX - 12.50 and stores it in OUT-NET, with extra decimals cut off (not rounded).
- L55: Otherwise:
  - L56: Copies 0 into OUT-NET.
- L58: Writes record OUT-REC to the output file.

## Where values can silently change

- L36: `WS-REG` rounds half away from zero. A result that does not fit loses its leading digits (holds 999999.99 at most). A migration must reproduce this exactly.
- L37: `WS-OT` rounds half away from zero. A result that does not fit loses its leading digits (holds 999999.99 at most). A migration must reproduce this exactly.
- L39: `WS-REG` rounds half away from zero. A result that does not fit loses its leading digits (holds 999999.99 at most). A migration must reproduce this exactly.
- L42: `WS-GROSS` truncates extra decimals. A result that does not fit loses its leading digits (holds 999999.99 at most). A migration must reproduce this exactly.
- L45: `WS-TAX` rounds half away from zero. A result that does not fit loses its leading digits (holds 999999.99 at most). A migration must reproduce this exactly.
- L47: `WS-TAX` rounds half away from zero. A result that does not fit loses its leading digits (holds 999999.99 at most). A migration must reproduce this exactly.
- L49: `WS-TAX` rounds half away from zero. A result that does not fit loses its leading digits (holds 999999.99 at most). A migration must reproduce this exactly.
- L54: `OUT-NET` truncates extra decimals. A result that does not fit loses its leading digits (holds +/-999999.99 at most). A migration must reproduce this exactly.

## Needs human review

- Every statement was recognized.
