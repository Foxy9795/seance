       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRICER IS INITIAL.
      * Line total with a discount by code. RETURN-CODE 1 means an
      * unknown code, 2 means the total did not fit.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE       PIC V99 VALUE 0.
       LINKAGE SECTION.
       01  LK-ARGS.
           05  LK-QTY    PIC 9(3).
           05  LK-PRICE  PIC 9(4)V99.
           05  LK-CODE   PIC X.
           05  LK-TOTAL  PIC 9(7)V99.
       PROCEDURE DIVISION USING LK-ARGS.
       PRICE-IT.
           MOVE 0 TO RETURN-CODE
           EVALUATE LK-CODE
               WHEN 'A' MOVE .10 TO WS-RATE
               WHEN 'B' MOVE .25 TO WS-RATE
               WHEN ' ' MOVE 0 TO WS-RATE
               WHEN OTHER
                   MOVE 1 TO RETURN-CODE
                   MOVE 0 TO WS-RATE
           END-EVALUATE
           COMPUTE LK-TOTAL ROUNDED =
               LK-QTY * LK-PRICE * (1 - WS-RATE)
               ON SIZE ERROR
                   MOVE 0 TO LK-TOTAL
                   MOVE 2 TO RETURN-CODE
           END-COMPUTE
           GOBACK.
