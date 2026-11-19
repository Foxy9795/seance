       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYPOST.
      * Posts the day's payments to a DB2 accounts table: new accounts
      * are inserted, known ones updated, then every account over its
      * credit line is flagged through a cursor FOR UPDATE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PAYMENTS ASSIGN TO PAYIN
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  PAYMENTS.
       01  PAY-REC.
           05  PAY-ACCT       PIC X(6).
           05  PAY-OWNER      PIC X(12).
           05  PAY-AMOUNT     PIC S9(5)V99 SIGN LEADING SEPARATE.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE ACCTTAB END-EXEC.
       01  WS-EOF             PIC X VALUE 'N'.
       01  WS-CREDIT-IND      PIC S9(4) COMP.
       01  WS-COUNTS.
           05  WS-INSERTED    PIC 9(4) VALUE 0.
           05  WS-UPDATED     PIC 9(4) VALUE 0.
           05  WS-FLAGGED     PIC 9(4) VALUE 0.
           05  WS-ERRORS      PIC 9(4) VALUE 0.
       01  WS-SHOWN           PIC -(7)9.99.
           EXEC SQL DECLARE OVER CURSOR FOR
               SELECT ACCTNO, BALANCE, CREDIT
                 FROM ACCOUNTS
                WHERE BALANCE < 0 - VALUE(CREDIT, 0)
                ORDER BY ACCTNO
                  FOR UPDATE OF STATUS
           END-EXEC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO SQL-FAILED END-EXEC.
           OPEN INPUT PAYMENTS
           PERFORM UNTIL WS-EOF = 'Y'
               READ PAYMENTS
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM POST-ONE
               END-READ
           END-PERFORM
           CLOSE PAYMENTS
           PERFORM FLAG-OVER-LIMIT
           EXEC SQL COMMIT END-EXEC
           DISPLAY 'INSERTED ' WS-INSERTED ' UPDATED ' WS-UPDATED
                   ' FLAGGED ' WS-FLAGGED
           STOP RUN.
       POST-ONE.
           MOVE PAY-ACCT TO ACCTNO
           EXEC SQL
               SELECT BALANCE, CREDIT
                 INTO :BALANCE, :CREDIT :WS-CREDIT-IND
                 FROM ACCOUNTS
                WHERE ACCTNO = :ACCTNO
           END-EXEC
           IF SQLCODE = 100
               MOVE PAY-OWNER TO OWNER
               MOVE PAY-AMOUNT TO BALANCE
               MOVE 'NEW' TO ACCT-STATUS
               MOVE -1 TO WS-CREDIT-IND
               EXEC SQL
                   INSERT INTO ACCOUNTS
                       (ACCTNO, OWNER, BALANCE, CREDIT, STATUS)
                   VALUES (:ACCTNO, :OWNER, :BALANCE,
                           :CREDIT :WS-CREDIT-IND, :ACCT-STATUS)
               END-EXEC
               ADD 1 TO WS-INSERTED
           ELSE
               ADD PAY-AMOUNT TO BALANCE
               EXEC SQL
                   UPDATE ACCOUNTS
                      SET BALANCE = :BALANCE,
                          STATUS  = 'ACTIVE'
                    WHERE ACCTNO = :ACCTNO
               END-EXEC
               ADD 1 TO WS-UPDATED
           END-IF.
       FLAG-OVER-LIMIT.
           EXEC SQL OPEN OVER END-EXEC
           PERFORM UNTIL SQLCODE NOT = 0
               EXEC SQL
                   FETCH OVER INTO :ACCTNO, :BALANCE,
                                   :CREDIT :WS-CREDIT-IND
               END-EXEC
               IF SQLCODE = 0
                   EXEC SQL
                       UPDATE ACCOUNTS SET STATUS = 'OVERLIM'
                        WHERE CURRENT OF OVER
                   END-EXEC
                   ADD 1 TO WS-FLAGGED
                   MOVE BALANCE TO WS-SHOWN
                   DISPLAY 'OVER LIMIT ' ACCTNO ' ' WS-SHOWN
               END-IF
           END-PERFORM
           EXEC SQL CLOSE OVER END-EXEC.
       SQL-FAILED.
           ADD 1 TO WS-ERRORS
           DISPLAY 'SQL ERROR ' SQLCODE ' STATE ' SQLSTATE
           EXEC SQL ROLLBACK END-EXEC
           MOVE 8 TO RETURN-CODE
           STOP RUN.
