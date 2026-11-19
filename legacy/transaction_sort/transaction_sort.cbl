       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTDEMO.
      * Sorts transactions three ways and sorts a table in storage.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-IN  ASSIGN TO TRANSIN.
           SELECT BY-ACCT   ASSIGN TO BYACCT.
           SELECT BIG-ONES  ASSIGN TO BIGONES
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT WORK-SORT ASSIGN TO SORTWK1.
       DATA DIVISION.
       FILE SECTION.
       FD  TRANS-IN RECORDING MODE F.
       01  TRANS-REC.
           05  T-ACCT    PIC X(6).
           05  T-AMOUNT  PIC S9(5)V99 COMP-3.
           05  T-TYPE    PIC X.
           05  T-SEQ     PIC 9(4).
       FD  BY-ACCT RECORDING MODE F.
       01  BY-ACCT-REC   PIC X(15).
       FD  BIG-ONES.
       01  BIG-LINE      PIC X(40).
       SD  WORK-SORT.
       01  SORT-REC.
           05  S-ACCT    PIC X(6).
           05  S-AMOUNT  PIC S9(5)V99 COMP-3.
           05  S-TYPE    PIC X.
           05  S-SEQ     PIC 9(4).
       WORKING-STORAGE SECTION.
       01  WS-EOF        PIC X VALUE 'N'.
       01  WS-COUNT      PIC 9(4) VALUE 0.
       01  WS-TOTAL      PIC S9(7)V99 VALUE 0.
       01  WS-SHOWN      PIC -(6)9.99.
       01  WS-TABLE.
           05  WS-ENTRY OCCURS 5 TIMES.
               10  WS-CODE  PIC X(3).
               10  WS-RANK  PIC 99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT WORK-SORT ON ASCENDING KEY S-ACCT
                             DESCENDING KEY S-AMOUNT
               USING TRANS-IN GIVING BY-ACCT
           SORT WORK-SORT ON DESCENDING KEY S-AMOUNT
               INPUT PROCEDURE IS PICK-CREDITS
               OUTPUT PROCEDURE IS PRINT-BIG
           MOVE 'DOG04CAT02EEL05ANT01BAT02' TO WS-TABLE
           SORT WS-ENTRY ON ASCENDING KEY WS-RANK
           DISPLAY 'TABLE ' WS-TABLE
           DISPLAY 'COUNT ' WS-COUNT ' SORT-RETURN ' SORT-RETURN
           STOP RUN.
       PICK-CREDITS.
           OPEN INPUT TRANS-IN
           PERFORM UNTIL WS-EOF = 'Y'
               READ TRANS-IN
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       IF T-TYPE = 'C'
                           RELEASE SORT-REC FROM TRANS-REC
                       END-IF
               END-READ
           END-PERFORM
           CLOSE TRANS-IN.
       PRINT-BIG.
           OPEN OUTPUT BIG-ONES
           MOVE 'N' TO WS-EOF
           PERFORM UNTIL WS-EOF = 'Y'
               RETURN WORK-SORT
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       ADD S-AMOUNT TO WS-TOTAL
                       IF WS-COUNT <= 5
                           MOVE S-AMOUNT TO WS-SHOWN
                           MOVE SPACES TO BIG-LINE
                           STRING S-ACCT ' ' WS-SHOWN ' ' S-SEQ
                               DELIMITED BY SIZE INTO BIG-LINE
                           WRITE BIG-LINE
                       END-IF
               END-RETURN
           END-PERFORM
           MOVE WS-TOTAL TO WS-SHOWN
           MOVE SPACES TO BIG-LINE
           STRING 'TOTAL ' WS-SHOWN DELIMITED BY SIZE INTO BIG-LINE
           WRITE BIG-LINE
           CLOSE BIG-ONES.
