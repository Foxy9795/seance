       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCOUNTS.
      * Month-end account maintenance: compound interest on savings,
      * a tiered service fee on checking, and an overdraft check.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-IN  ASSIGN TO ACCTIN.
           SELECT ACCT-OUT ASSIGN TO ACCTOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCT-IN RECORDING MODE F.
           COPY ACCTREC.
       FD  ACCT-OUT RECORDING MODE F.
       01  OUT-REC.
           05  OUT-ACCT-NO      PIC X(8).
           05  OUT-NEW-BAL      PIC S9(7)V99.
           05  OUT-FEE          PIC 9(3)V99.
           05  OUT-INTEREST     PIC 9(5)V99.
           05  OUT-STATUS       PIC X(10).
           05  OUT-SHOWN        PIC $$,$$$,$$9.99-.
       WORKING-STORAGE SECTION.
       01  WS-FLAGS.
           05  WS-EOF           PIC X VALUE 'N'.
               88  END-OF-FILE  VALUE 'Y'.
       01  WS-WORK.
           05  WS-BAL           PIC S9(9)V9(4) COMP-3.
           05  WS-MONTH-RATE    PIC 9V9(6).
           05  WS-I             PIC 999.
           05  WS-COUNT         PIC 9(7) VALUE ZERO.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT  ACCT-IN
                OUTPUT ACCT-OUT
           PERFORM 8000-READ
           PERFORM 1000-PROCESS UNTIL END-OF-FILE
           CLOSE ACCT-IN ACCT-OUT
           GOBACK.
       1000-PROCESS.
           INITIALIZE OUT-REC
           MOVE ACCT-NO      TO OUT-ACCT-NO
           MOVE ACCT-BALANCE TO WS-BAL
           ADD 1 TO WS-COUNT
           EVALUATE TRUE
               WHEN SAVINGS
                   PERFORM 2000-INTEREST
               WHEN CHECKING
                   PERFORM 3000-FEE
               WHEN OTHER
                   MOVE 'UNKNOWN' TO OUT-STATUS
           END-EVALUATE
           IF WS-BAL < ZERO
               IF 0 - WS-BAL > ACCT-LIMIT
                   MOVE 'OVER-LIMIT' TO OUT-STATUS
               ELSE
                   MOVE 'OVERDRAWN' TO OUT-STATUS
               END-IF
           ELSE
               IF OUT-STATUS = SPACES
                   MOVE 'OK' TO OUT-STATUS
               END-IF
           END-IF
           COMPUTE OUT-NEW-BAL = WS-BAL
           MOVE OUT-NEW-BAL TO OUT-SHOWN
           WRITE OUT-REC
           PERFORM 8000-READ.
       2000-INTEREST.
           COMPUTE WS-MONTH-RATE = ACCT-RATE / 12
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > ACCT-MONTHS
               COMPUTE WS-BAL ROUNDED = WS-BAL * (1 + WS-MONTH-RATE)
           END-PERFORM
           COMPUTE OUT-INTEREST ROUNDED = WS-BAL - ACCT-BALANCE
               ON SIZE ERROR MOVE 99999.99 TO OUT-INTEREST
           END-COMPUTE.
       3000-FEE.
           EVALUATE TRUE
               WHEN WS-BAL >= 2500
                   MOVE 0 TO OUT-FEE
               WHEN WS-BAL >= 500
                   MOVE 4.50 TO OUT-FEE
               WHEN OTHER
                   MOVE 12.00 TO OUT-FEE
           END-EVALUATE
           SUBTRACT OUT-FEE FROM WS-BAL.
       8000-READ.
           READ ACCT-IN
               AT END SET END-OF-FILE TO TRUE
           END-READ.
