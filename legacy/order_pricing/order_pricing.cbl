       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDPRICE.
      * Prices orders by calling a pricing module and a counter module.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDERS ASSIGN TO ORDERIN
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT PRICED ASSIGN TO PRICEOUT
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  ORDERS.
       01  ORDER-REC.
           05  O-ID      PIC X(5).
           05  O-QTY     PIC 9(3).
           05  O-PRICE   PIC 9(4)V99.
           05  O-CODE    PIC X.
       FD  PRICED.
       01  PRICED-REC.
           05  P-ID      PIC X(5).
           05  FILLER    PIC X VALUE SPACE.
           05  P-TOTAL   PIC Z(6)9.99.
           05  FILLER    PIC X VALUE SPACE.
           05  P-RC      PIC 9.
           05  FILLER    PIC X VALUE SPACE.
           05  P-SEEN    PIC 9(4).
       WORKING-STORAGE SECTION.
       01  WS-EOF        PIC X VALUE 'N'.
       01  WS-ARGS.
           05  WS-QTY    PIC 9(3).
           05  WS-PRICE  PIC 9(4)V99.
           05  WS-CODE   PIC X.
           05  WS-TOTAL  PIC 9(7)V99.
       01  WS-SEEN       PIC 9(4).
       01  WS-MISSING    PIC X VALUE 'N'.
       01  WS-BLANK      PIC X(5) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ORDERS OUTPUT PRICED
           PERFORM UNTIL WS-EOF = 'Y'
               READ ORDERS
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM PRICE-ONE
               END-READ
           END-PERFORM
           CALL 'NOSUCHPG' USING WS-ARGS
               ON EXCEPTION MOVE 'Y' TO WS-MISSING
           END-CALL
           DISPLAY 'MISSING MODULE HANDLED: ' WS-MISSING
           CANCEL 'COUNTER'
           CALL 'COUNTER' USING WS-SEEN WS-BLANK
           DISPLAY 'AFTER CANCEL: ' WS-SEEN
           CLOSE ORDERS PRICED
           GOBACK.
       PRICE-ONE.
           MOVE O-QTY TO WS-QTY
           MOVE O-PRICE TO WS-PRICE
           MOVE O-CODE TO WS-CODE
           CALL 'PRICER' USING BY REFERENCE WS-ARGS
           MOVE RETURN-CODE TO P-RC
           CALL 'COUNTER' USING BY REFERENCE WS-SEEN
                                BY CONTENT O-ID
           MOVE O-ID TO P-ID
           MOVE WS-TOTAL TO P-TOTAL
           MOVE WS-SEEN TO P-SEEN
           WRITE PRICED-REC.
