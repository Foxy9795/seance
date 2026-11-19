# Spec: TRANSACTION_SORT (from `legacy/transaction_sort/transaction_sort.cbl`)

Purpose, from the source comment: Sorts transactions three ways and sorts a table in storage.

The program reads `TRANSIN` (fixed-length records), writes `BYACCT` (fixed-length records), writes `BIGONES` (text lines). Source format: fixed (columns 8-72).

## Input file TRANSIN: TRANS-REC (15 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| T-ACCT | 1-6 | text, 6 characters |
| T-AMOUNT | 7-10 | number, 5 integer digit(s), 2 decimal(s), unsigned, stored as packed decimal (COMP-3) in 4 bytes |
| T-TYPE | 11-11 | text, 1 characters |
| T-SEQ | 12-15 | number, 4 integer digit(s), 0 decimal(s), unsigned |

## Output file BYACCT: BY-ACCT-REC (15 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| BY-ACCT-REC | 1-15 | text, 15 characters |

## Output file BIGONES: BIG-LINE (40 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| BIG-LINE | 1-40 | text, 40 characters |

## Output file SORTWK1: SORT-REC (15 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| S-ACCT | 1-6 | text, 6 characters |
| S-AMOUNT | 7-10 | number, 5 integer digit(s), 2 decimal(s), unsigned, stored as packed decimal (COMP-3) in 4 bytes |
| S-TYPE | 11-11 | text, 1 characters |
| S-SEQ | 12-15 | number, 4 integer digit(s), 0 decimal(s), unsigned |

## Behavior by paragraph


### MAIN-PARA (line 40)

- L41: (not summarized) `SORT WORK-SORT ON ASCENDING KEY S-ACCT`
        - L42: (not summarized) `DESCENDING KEY S-AMOUNT`
  - L43: (not summarized) `USING TRANS-IN GIVING BY-ACCT`
- L44: (not summarized) `SORT WORK-SORT ON DESCENDING KEY S-AMOUNT`
  - L45: (continued) opens PROCEDURE IS PICK-CREDITS for reading.
  - L46: (continued) opens PROCEDURE IS PRINT-BIG for writing.
- L47: Copies 'DOG04CAT02EEL05ANT01BAT02' into WS-TABLE.
- L48: (not summarized) `SORT WS-ENTRY ON ASCENDING KEY WS-RANK`
- L49: Shows 'TABLE ' WS-TABLE on the console.
- L50: Shows 'COUNT ' WS-COUNT ' SORT-RETURN ' SORT-RETURN on the console.
- L51: Ends the program.

### PICK-CREDITS (line 52)

- L53: Opens files (input trans-in).
- L54: Repeats the steps below until WS-EOF = 'Y'.
  - L55: Reads the next record from TRANS-IN.
    - L56: When the file is exhausted: copies 'Y' into WS-EOF.
    - L57: (not summarized) `NOT AT END`
      - L58: If T-TYPE = 'C':
        - L59: (not summarized) `RELEASE SORT-REC FROM TRANS-REC`
- L63: Closes TRANS-IN.

### PRINT-BIG (line 64)

- L65: Opens files (output big-ones).
- L66: Copies 'N' into WS-EOF.
- L67: Repeats the steps below until WS-EOF = 'Y'.
  - L68: (not summarized) `RETURN WORK-SORT`
    - L69: When the file is exhausted: copies 'Y' into WS-EOF.
    - L70: (not summarized) `NOT AT END`
      - L71: Adds 1 to WS-COUNT.
      - L72: Adds S-AMOUNT to WS-TOTAL.
      - L73: If WS-COUNT <= 5:
        - L74: Copies S-AMOUNT into WS-SHOWN.
        - L75: Copies SPACES into BIG-LINE.
        - L76: (not summarized) `STRING S-ACCT ' ' WS-SHOWN ' ' S-SEQ`
          - L77: (not summarized) `DELIMITED BY SIZE INTO BIG-LINE`
        - L78: Writes record BIG-LINE to the output file.
  - L80: (not summarized) `END-RETURN`
- L82: Copies WS-TOTAL into WS-SHOWN.
- L83: Copies SPACES into BIG-LINE.
- L84: (not summarized) `STRING 'TOTAL ' WS-SHOWN DELIMITED BY SIZE INTO BIG-LINE`
- L85: Writes record BIG-LINE to the output file.
- L86: Closes BIG-ONES.

## Where values can silently change

- None detected.

## Needs human review

- line 41: `SORT WORK-SORT ON ASCENDING KEY S-ACCT` was not summarized
- line 42: `DESCENDING KEY S-AMOUNT` was not summarized
- line 43: `USING TRANS-IN GIVING BY-ACCT` was not summarized
- line 44: `SORT WORK-SORT ON DESCENDING KEY S-AMOUNT` was not summarized
- line 48: `SORT WS-ENTRY ON ASCENDING KEY WS-RANK` was not summarized
- line 57: `NOT AT END` was not summarized
- line 59: `RELEASE SORT-REC FROM TRANS-REC` was not summarized
- line 68: `RETURN WORK-SORT` was not summarized
- line 70: `NOT AT END` was not summarized
- line 76: `STRING S-ACCT ' ' WS-SHOWN ' ' S-SEQ` was not summarized
- line 77: `DELIMITED BY SIZE INTO BIG-LINE` was not summarized
- line 80: `END-RETURN` was not summarized
- line 84: `STRING 'TOTAL ' WS-SHOWN DELIMITED BY SIZE INTO BIG-LINE` was not summarized
