# Spec: INVENTORY (from `legacy/inventory/inventory.cbl`)

Purpose, from the source comment: Daily stock update. Shortfalls become backorders and stock floors at zero.

The program reads `INPUT.DAT` (text lines), writes `OUTPUT.DAT` (text lines). Source format: free.

## Input file INPUT.DAT: IN-REC (29 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| IN-SKU | 1-8 | text, 8 characters |
| IN-ON-HAND | 9-14 | number, 5 integer digit(s), 0 decimal(s), separate +/- character first |
| IN-RECEIVED | 15-19 | number, 5 integer digit(s), 0 decimal(s), unsigned |
| IN-SHIPPED | 20-24 | number, 5 integer digit(s), 0 decimal(s), unsigned |
| IN-REORDER | 25-29 | number, 5 integer digit(s), 0 decimal(s), unsigned |

## Output file OUTPUT.DAT: OUT-REC (19 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| OUT-SKU | 1-8 | text, 8 characters |
| OUT-NEW-ON-HAND | 9-13 | number, 5 integer digit(s), 0 decimal(s), unsigned |
| OUT-BACKORDER | 14-18 | number, 5 integer digit(s), 0 decimal(s), unsigned |
| OUT-FLAG | 19-19 | text, 1 characters |

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

- L30: Copies IN-SKU into OUT-SKU.
- L31: Calculates IN-ON-HAND + IN-RECEIVED - IN-SHIPPED and stores it in WS-NET, with extra decimals cut off (not rounded).
- L32: If WS-NET < 0:
  - L33: Calculates 0 - WS-NET and stores it in OUT-BACKORDER, with extra decimals cut off (not rounded).
  - L34: Copies 0 into OUT-NEW-ON-HAND.
- L35: Otherwise:
  - L36: Copies 0 into OUT-BACKORDER.
  - L37: Copies WS-NET into OUT-NEW-ON-HAND. (OUT-NEW-ON-HAND holds 99999 at most; larger values lose their leading digits)
- L39: If OUT-NEW-ON-HAND <= IN-REORDER:
  - L40: Copies "R" into OUT-FLAG.
- L41: Otherwise:
  - L42: Copies " " into OUT-FLAG.
- L44: Writes record OUT-REC to the output file.

## Where values can silently change

- L31: `WS-NET` truncates extra decimals. A result that does not fit loses its leading digits (holds +/-999999 at most). A migration must reproduce this exactly.
- L33: `OUT-BACKORDER` truncates extra decimals. A result that does not fit loses its leading digits (holds 99999 at most). A migration must reproduce this exactly.

## Needs human review

- Every statement was recognized.
