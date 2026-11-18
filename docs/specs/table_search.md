# Spec: TABLE_SEARCH (from `legacy/table_search/table_search.cbl`)

The program reads `ACCTREC` (fixed-length records). Source format: fixed (columns 8-72).

## Input file ACCTREC: ACCT-FIELDS (170 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| ACCT-FIELDS | 1-170 | text, 170 characters |

## Behavior by paragraph


### OPEN-FILES (line 47)

- L48: Opens files (input acct-rec).

### LOAD-TABLES (line 50)

- L51: Runs paragraph READ-RECORD.
- L52: (not summarized) `PERFORM VARYING TABLE-VAR FROM 1 BY 1`
- L53: (not summarized) `UNTIL TABLE-VAR = TABLE-MAX OR END-OF-FILE`
  - L54: (not summarized) `MOVE ACCT-FIELDS TO ACCT-TABLE-ITEM (TABLE-VAR)`
  - L55: Runs paragraph READ-RECORD.

### SEARCH-RECORD (line 58)

- L59: (not summarized) `SET TABLE-IDX TO 1.`
- L60: (not summarized) `SEARCH ALL ACCT-TABLE-ITEM`
  - L61: When the file is exhausted: shows "NOT FOUND" on the console.
  - L62: Case: ACCT-NO (TABLE-IDX) = 18011809.
    - L63: Shows "USER WITH ACCT NO 18011809 IS FOUND!" on the console.

### CLOSE-STOP (line 65)

- L66: Closes ACCT-REC.
- L67: Ends the program.

### READ-RECORD (line 69)

- L70: Reads the next record from ACCT-REC.
  - L71: When the file is exhausted: makes condition END-OF-FILE true.

## Where values can silently change

- None detected.

## Needs human review

- line 52: `PERFORM VARYING TABLE-VAR FROM 1 BY 1` was not summarized
- line 53: `UNTIL TABLE-VAR = TABLE-MAX OR END-OF-FILE` was not summarized
- line 54: `MOVE ACCT-FIELDS TO ACCT-TABLE-ITEM (TABLE-VAR)` was not summarized
- line 59: `SET TABLE-IDX TO 1.` was not summarized
- line 60: `SEARCH ALL ACCT-TABLE-ITEM` was not summarized
