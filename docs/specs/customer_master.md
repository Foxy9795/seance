# Spec: CUSTOMER_MASTER (from `legacy/customer_master/customer_master.cbl`)

Purpose, from the source comment: Applies transactions to an indexed customer master (VSAM KSDS style): add, change, delete, then lists by region.

The program reads `CUSTMAST` (fixed-length records), reads `TRANSIN` (text lines), writes `CUSTMAST` (fixed-length records), writes `RPTOUT` (text lines). Source format: fixed (columns 8-72).

## Input file CUSTMAST: M-REC (21 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| M-ID | 1-5 | text, 5 characters |
| M-REGION | 6-7 | text, 2 characters |
| M-BALANCE | 8-11 | number, 5 integer digit(s), 2 decimal(s), unsigned, stored as packed decimal (COMP-3) in 4 bytes |
| M-NAME | 12-21 | text, 10 characters |

## Input file TRANSIN: T-REC (26 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| T-ACTION | 1-1 | text, 1 characters |
| T-ID | 2-6 | text, 5 characters |
| T-REGION | 7-8 | text, 2 characters |
| T-AMOUNT | 9-16 | number, 5 integer digit(s), 2 decimal(s), separate +/- character first |
| T-NAME | 17-26 | text, 10 characters |

## Output file RPTOUT: RPT-LINE (60 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| RPT-LINE | 1-60 | text, 60 characters |

## Behavior by paragraph


### MAIN-PARA (line 45)

- L46: Opens files (i-o master).
- L47: If WS-FS NOT = '00':
  - L48: Shows 'OPEN FAILED ' WS-FS on the console.
  - L49: Ends the program.
- L51: Opens files (input trans output report-out).
- L52: Repeats the steps below until WS-EOF = 'Y'.
  - L53: Reads the next record from TRANS.
    - L54: When the file is exhausted: copies 'Y' into WS-EOF.
    - L55: When there is another record: runs paragraph APPLY-ONE.
- L58: Runs paragraph LIST-BY-REGION.
- L59: Shows 'ADDED ' WS-ADDED ' CHANGED ' WS-CHANGED on the console.
    - L60: (not summarized) `' DELETED ' WS-DELETED ' REJECTED ' WS-REJECTS`
- L61: Closes MASTER and TRANS and REPORT-OUT.
- L62: Ends the program.

### APPLY-ONE (line 63)

- L64: Copies T-ID into M-ID.
- L65: (not summarized) `EVALUATE T-ACTION`
  - L66: Case: 'A'.
    - L67: Copies T-REGION into M-REGION.
    - L68: Copies T-AMOUNT into M-BALANCE. (M-BALANCE holds +/-99999.99 at most; larger values lose their leading digits)
    - L69: Copies T-NAME into M-NAME.
    - L70: Writes record M-REC to the output file.
      - L71: (not summarized) `INVALID KEY ADD 1 TO WS-REJECTS`
      - L72: (not summarized) `NOT INVALID KEY ADD 1 TO WS-ADDED`
  - L74: Case: 'C'.
    - L75: Reads the next record from MASTER.
      - L76: (not summarized) `INVALID KEY ADD 1 TO WS-REJECTS`
      - L77: (not summarized) `NOT INVALID KEY`
        - L78: Adds T-AMOUNT to M-BALANCE.
        - L79: (not summarized) `REWRITE M-REC`
        - L80: Adds 1 to WS-CHANGED.
  - L82: Case: 'D'.
    - L83: (not summarized) `DELETE MASTER RECORD`
      - L84: (not summarized) `INVALID KEY ADD 1 TO WS-REJECTS`
      - L85: (not summarized) `NOT INVALID KEY ADD 1 TO WS-DELETED`
    - L86: (not summarized) `END-DELETE`
  - L87: In every other case:
    - L88: Adds 1 to WS-REJECTS.

### LIST-BY-REGION (line 90)

- L91: Copies LOW-VALUES into M-REGION.
- L92: (not summarized) `START MASTER KEY IS NOT LESS THAN M-REGION`
  - L93: (not summarized) `INVALID KEY MOVE 'Y' TO WS-EOF`
  - L94: (not summarized) `NOT INVALID KEY MOVE 'N' TO WS-EOF`
- L95: (not summarized) `END-START`
- L96: Repeats the steps below until WS-EOF = 'Y'.
  - L97: (not summarized) `READ MASTER NEXT RECORD`
    - L98: When the file is exhausted: copies 'Y' into WS-EOF.
    - L99: (not summarized) `NOT AT END`
      - L100: Copies M-BALANCE into WS-SHOWN.
      - L101: Copies SPACES into RPT-LINE.
      - L102: (not summarized) `STRING M-REGION ' ' M-ID ' ' M-NAME ' ' WS-SHOWN`
        - L103: (not summarized) `' ' WS-FS DELIMITED BY SIZE INTO RPT-LINE`
      - L104: Writes record RPT-LINE to the output file.

## Where values can silently change

- None detected.

## Needs human review

- line 60: `' DELETED ' WS-DELETED ' REJECTED ' WS-REJECTS` was not summarized
- line 65: `EVALUATE T-ACTION` was not summarized
- line 71: `INVALID KEY ADD 1 TO WS-REJECTS` was not summarized
- line 72: `NOT INVALID KEY ADD 1 TO WS-ADDED` was not summarized
- line 76: `INVALID KEY ADD 1 TO WS-REJECTS` was not summarized
- line 77: `NOT INVALID KEY` was not summarized
- line 79: `REWRITE M-REC` was not summarized
- line 83: `DELETE MASTER RECORD` was not summarized
- line 84: `INVALID KEY ADD 1 TO WS-REJECTS` was not summarized
- line 85: `NOT INVALID KEY ADD 1 TO WS-DELETED` was not summarized
- line 86: `END-DELETE` was not summarized
- line 92: `START MASTER KEY IS NOT LESS THAN M-REGION` was not summarized
- line 93: `INVALID KEY MOVE 'Y' TO WS-EOF` was not summarized
- line 94: `NOT INVALID KEY MOVE 'N' TO WS-EOF` was not summarized
- line 95: `END-START` was not summarized
- line 97: `READ MASTER NEXT RECORD` was not summarized
- line 99: `NOT AT END` was not summarized
- line 102: `STRING M-REGION ' ' M-ID ' ' M-NAME ' ' WS-SHOWN` was not summarized
- line 103: `' ' WS-FS DELIMITED BY SIZE INTO RPT-LINE` was not summarized
