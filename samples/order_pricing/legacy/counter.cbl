       IDENTIFICATION DIVISION.
       PROGRAM-ID. COUNTER.
      * Keeps a running count between calls (storage is not reset).
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CALLS      PIC 9(4) VALUE 0.
       LINKAGE SECTION.
       01  LK-SEEN       PIC 9(4).
       01  LK-ID         PIC X(5).
       PROCEDURE DIVISION USING LK-SEEN LK-ID.
       COUNT-IT.
           ADD 1 TO WS-CALLS
           MOVE WS-CALLS TO LK-SEEN
           IF LK-ID = SPACES
               EXIT PROGRAM
           END-IF
           MOVE 'XXXXX' TO LK-ID
           EXIT PROGRAM.
