       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTINQ.
      * CICS customer inquiry and payment, pseudo-conversational: the
      * first run sends the screen; each later run reads what the user
      * typed, looks the customer up in the CUSTFILE KSDS, applies a
      * payment when asked, and ends on PF3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY DFHAID.
           COPY CUSTMAP.
       01  WS-RESP            PIC S9(8) COMP.
       01  WS-CUST-KEY        PIC X(6).
       01  WS-CUST-REC.
           05  CUST-NO        PIC X(6).
           05  CUST-NAME      PIC X(20).
           05  CUST-BALANCE   PIC S9(7)V99 COMP-3.
           05  CUST-LAST-PAY  PIC 9(5)V99.
       01  WS-COUNT-ITEM      PIC S9(4) COMP.
       01  WS-AUDIT.
           05  AUD-CUSTNO     PIC X(6).
           05  AUD-AMOUNT     PIC 9(5)V99.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  CA-STATE       PIC X.
           05  CA-SCREENS     PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF EIBCALEN = 0
               MOVE LOW-VALUES TO CUSTMO
               MOVE 'ENTER A CUSTOMER NUMBER' TO MSG-TEXT
               PERFORM SEND-SCREEN
               MOVE 'S' TO CA-STATE
               MOVE 0 TO CA-SCREENS
               EXEC CICS RETURN TRANSID('CINQ')
                    COMMAREA(DFHCOMMAREA) LENGTH(4)
               END-EXEC
           END-IF
           ADD 1 TO CA-SCREENS
      * CLEAR and the PA keys send no data, so look at the key first.
           EVALUATE EIBAID
               WHEN DFHPF3
                   MOVE 'GOODBYE' TO MSG-TEXT
                   PERFORM SEND-SCREEN
                   EXEC CICS RETURN END-EXEC
               WHEN DFHCLEAR
                   MOVE SPACES TO CUSTMSG
                   MOVE 'SCREEN CLEARED' TO MSG-TEXT
               WHEN DFHENTER
                   EXEC CICS RECEIVE MAP('CUSTM') MAPSET('CUSTSET')
                        INTO(CUSTMI) RESP(WS-RESP)
                   END-EXEC
                   IF WS-RESP = DFHRESP(NORMAL)
                       PERFORM LOOK-UP
                   ELSE
                       MOVE 'NOTHING RECEIVED' TO MSG-TEXT
                   END-IF
               WHEN OTHER
                   MOVE 'INVALID KEY PRESSED' TO MSG-TEXT
           END-EVALUATE
           PERFORM SEND-SCREEN
           EXEC CICS RETURN TRANSID('CINQ')
                COMMAREA(DFHCOMMAREA) LENGTH(4)
           END-EXEC.
       LOOK-UP.
           MOVE CUSTNOI TO WS-CUST-KEY MSG-CUSTNO
           EXEC CICS READ FILE('CUSTFILE') INTO(WS-CUST-REC)
                RIDFLD(WS-CUST-KEY) UPDATE RESP(WS-RESP)
           END-EXEC
           EVALUATE WS-RESP
               WHEN DFHRESP(NORMAL)
                   MOVE CUST-NAME TO MSG-NAME
                   IF ACTIONI = 'P' AND AMOUNTI > 0
                       SUBTRACT AMOUNTI FROM CUST-BALANCE
                       MOVE AMOUNTI TO CUST-LAST-PAY
                       EXEC CICS REWRITE FILE('CUSTFILE')
                            FROM(WS-CUST-REC) RESP(WS-RESP)
                       END-EXEC
                       MOVE CUST-NO TO AUD-CUSTNO
                       MOVE AMOUNTI TO AUD-AMOUNT
                       EXEC CICS WRITEQ TS QUEUE('PAYAUDIT')
                            FROM(WS-AUDIT) ITEM(WS-COUNT-ITEM)
                       END-EXEC
                       MOVE 'PAYMENT APPLIED' TO MSG-TEXT
                   ELSE
                       MOVE 'CUSTOMER FOUND' TO MSG-TEXT
                   END-IF
                   MOVE CUST-BALANCE TO MSG-BALANCE
               WHEN DFHRESP(NOTFND)
                   MOVE SPACES TO MSG-NAME
                   MOVE 0 TO MSG-BALANCE
                   MOVE 'NO SUCH CUSTOMER' TO MSG-TEXT
               WHEN OTHER
                   MOVE 'FILE ERROR' TO MSG-TEXT
           END-EVALUATE.
       SEND-SCREEN.
           EXEC CICS SEND TEXT FROM(CUSTMSG) ERASE END-EXEC.
