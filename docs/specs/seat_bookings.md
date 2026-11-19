# Spec: SEAT_BOOKINGS (from `legacy/seat_bookings/seat_bookings.cbl`)

Purpose, from the source comment: Seat bookings in a relative file: slot number = seat number.

The program reads `SEATFILE` (fixed-length records), reads `REQFILE` (text lines), writes `SEATFILE` (fixed-length records). Source format: fixed (columns 8-72).

## Input file SEATFILE: SEAT-REC (13 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| S-NAME | 1-8 | text, 8 characters |
| S-PAID | 9-13 | number, 3 integer digit(s), 2 decimal(s), unsigned |

## Input file REQFILE: REQ-REC (17 bytes per record)

| Field | Bytes | Meaning |
| --- | --- | --- |
| R-ACTION | 1-1 | text, 1 characters |
| R-SEAT | 2-4 | number, 3 integer digit(s), 0 decimal(s), unsigned |
| R-NAME | 5-12 | text, 8 characters |
| R-PAID | 13-17 | number, 3 integer digit(s), 2 decimal(s), unsigned |

## Behavior by paragraph


### MAIN-PARA (line 32)

- L33: Opens files (i-o seats).
- L34: Opens files (input reqs).
- L35: Repeats the steps below until WS-EOF = 'Y'.
  - L36: Reads the next record from REQS.
    - L37: When the file is exhausted: copies 'Y' into WS-EOF.
    - L38: When there is another record: runs paragraph ONE-REQUEST.
- L41: Copies 1 into WS-SEAT.
- L42: Copies 'N' into WS-EOF.
- L43: (not summarized) `START SEATS KEY IS >= WS-SEAT`
  - L44: (not summarized) `INVALID KEY MOVE 'Y' TO WS-EOF`
- L45: (not summarized) `END-START`
- L46: Repeats the steps below until WS-EOF = 'Y'.
  - L47: (not summarized) `READ SEATS NEXT`
    - L48: When the file is exhausted: copies 'Y' into WS-EOF.
    - L49: (not summarized) `NOT AT END`
      - L50: Adds 1 to WS-TAKEN.
      - L51: Shows 'SEAT ' WS-SEAT ' ' S-NAME ' ' S-PAID on the console.
- L54: Shows 'TAKEN ' WS-TAKEN on the console.
- L55: Closes SEATS and REQS.
- L56: Ends the program.

### ONE-REQUEST (line 57)

- L58: Copies R-SEAT into WS-SEAT. (WS-SEAT holds 9999 at most; larger values lose their leading digits)
- L59: If R-ACTION = 'B':
  - L60: Copies R-NAME into S-NAME.
  - L61: Copies R-PAID into S-PAID. (S-PAID holds 999.99 at most; larger values lose their leading digits)
  - L62: Writes record SEAT-REC to the output file.
    - L63: (not summarized) `INVALID KEY DISPLAY 'TAKEN OR BAD ' R-SEAT ' ' WS-FS`
- L65: Otherwise:
  - L66: (not summarized) `DELETE SEATS`
    - L67: (not summarized) `INVALID KEY DISPLAY 'NOT BOOKED ' R-SEAT ' ' WS-FS`
  - L68: (not summarized) `END-DELETE`

## Where values can silently change

- None detected.

## Needs human review

- line 43: `START SEATS KEY IS >= WS-SEAT` was not summarized
- line 44: `INVALID KEY MOVE 'Y' TO WS-EOF` was not summarized
- line 45: `END-START` was not summarized
- line 47: `READ SEATS NEXT` was not summarized
- line 49: `NOT AT END` was not summarized
- line 63: `INVALID KEY DISPLAY 'TAKEN OR BAD ' R-SEAT ' ' WS-FS` was not summarized
- line 66: `DELETE SEATS` was not summarized
- line 67: `INVALID KEY DISPLAY 'NOT BOOKED ' R-SEAT ' ' WS-FS` was not summarized
- line 68: `END-DELETE` was not summarized
