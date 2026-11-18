# Spec: ACCOUNT_REPORT (from `legacy/account_report/account_report.cbl`)

Purpose, from the source comment: MOVE LAST-NAME      TO  LAST-NAME-O.

The program reads `ACCTREC` (fixed-length records), writes `PRTLINE` (fixed-length records). Source format: fixed (columns 8-72).

Note: line 7: added the period after the PROGRAM-ID name, which IBM COBOL lets you leave out.

## Output file PRTLINE: PRINT-REC (62 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| ACCT-NO-O | 1-8 | text, 8 characters |
| FILLER | 9-10 | text, 2 characters |
| LAST-NAME-O | 11-30 | text, 20 characters |
| FILLER | 31-32 | text, 2 characters |
| ACCT-LIMIT-O | 33-45 | number shown with editing, picture `$$,$$$,$$9.99` |
| FILLER | 46-47 | text, 2 characters |
| ACCT-BALANCE-O | 48-60 | number shown with editing, picture `$$,$$$,$$9.99` |
| FILLER | 61-62 | text, 2 characters |

## Input file ACCTREC: ACCT-FIELDS (170 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| ACCT-NO | 1-8 | text, 8 characters |
| ACCT-LIMIT | 9-13 | number, 7 integer digit(s), 2 decimal(s), unsigned, stored as packed decimal (COMP-3) in 5 bytes |
| ACCT-BALANCE | 14-18 | number, 7 integer digit(s), 2 decimal(s), unsigned, stored as packed decimal (COMP-3) in 5 bytes |
| LAST-NAME | 19-38 | text, 20 characters |
| FIRST-NAME | 39-53 | text, 15 characters |
| STREET-ADDR | 54-78 | text, 25 characters |
| CITY-COUNTY | 79-98 | text, 20 characters |
| USA-STATE | 99-113 | text, 15 characters |
| RESERVED | 114-120 | text, 7 characters |
| COMMENTS | 121-170 | text, 50 characters |

## Behavior by paragraph


### OPEN-FILES (line 118)

- L119: Opens files (input acct-rec).
- L120: Opens files (output print-line).

### WRITE-HEADERS (line 122)

- L123: Copies FUNCTION CURRENT-DATE into WS-CURRENT-DATE-DATA.
- L124: Copies WS-CURRENT-YEAR into HDR-YR. (HDR-YR holds 9999 at most; larger values lose their leading digits)
- L125: Copies WS-CURRENT-MONTH into HDR-MO.
- L126: Copies WS-CURRENT-DAY into HDR-DAY.
- L127: Writes record PRINT-REC (taken from HEADER-1) to the output file.
- L128: Writes record PRINT-REC (taken from HEADER-2) to the output file.
- L129: Copies SPACES into PRINT-REC.
- L130: Writes record PRINT-REC to the output file.
- L131: Writes record PRINT-REC (taken from HEADER-3) to the output file.
- L132: Writes record PRINT-REC (taken from HEADER-4) to the output file.
- L133: Copies SPACES into PRINT-REC.

### READ-NEXT-RECORD (line 135)

- L136: Runs paragraph READ-RECORD.
- L137: Repeats the steps below until LASTREC = 'Y'.
  - L138: Runs paragraph LIMIT-BALANCE-TOTAL.
  - L139: Runs paragraph WRITE-RECORD.
  - L140: Runs paragraph READ-RECORD.
- L142: (not summarized) `.`

### WRITE-TLIMIT-TBALANCE (line 143)

- L144: Copies TLIMIT into TLIMIT-O.
- L145: Copies TBALANCE into TBALANCE-O.
- L146: Writes record PRINT-REC (taken from TRAILER-1) to the output file.
- L147: Writes record PRINT-REC (taken from TRAILER-2) to the output file.

### CLOSE-STOP (line 149)

- L150: Closes ACCT-REC.
- L151: Closes PRINT-LINE.
- L152: Ends the program.

### READ-RECORD (line 154)

- L155: Reads the next record from ACCT-REC.
  - L156: When the file is exhausted: copies 'Y' into LASTREC.

### LIMIT-BALANCE-TOTAL (line 159)

- L160: Calculates TLIMIT + ACCT-LIMIT END-COMPUTE and stores it in TLIMIT, with extra decimals cut off (not rounded).
- L161: Calculates TBALANCE + ACCT-BALANCE END-COMPUTE and stores it in TBALANCE, with extra decimals cut off (not rounded).
- L162: (not summarized) `.`

### WRITE-RECORD (line 164)

- L165: Copies ACCT-NO into ACCT-NO-O.
- L166: Copies ACCT-LIMIT into ACCT-LIMIT-O.
- L167: Copies ACCT-BALANCE into ACCT-BALANCE-O.
- L169: (not summarized) `MOVE LAST-NAME(1:1) TO  LAST-NAME-O(1:1).`
- L170: (not summarized) `MOVE FUNCTION LOWER-CASE(LAST-NAME(2:19))`
          - L171: (not summarized) `TO LAST-NAME-O(2:19).`
- L172: Writes record PRINT-REC to the output file.

## Where values can silently change

- L161: `TBALANCE` truncates extra decimals. A result that does not fit loses its leading digits (holds +/-999999999.99 at most). A migration must reproduce this exactly.

## Needs human review

- line 142: `.` was not summarized
- line 162: `.` was not summarized
- line 169: `MOVE LAST-NAME(1:1) TO  LAST-NAME-O(1:1).` was not summarized
- line 170: `MOVE FUNCTION LOWER-CASE(LAST-NAME(2:19))` was not summarized
- line 171: `TO LAST-NAME-O(2:19).` was not summarized
