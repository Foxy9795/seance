       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVOICE.
      * Prices invoice lines: quantity times unit price, a discount
      * band by quantity, VAT by product class, and a total line.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LINES-IN ASSIGN TO "LINES.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT INVOICE-OUT ASSIGN TO "INVOICE.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  LINES-IN.
       COPY INVLINE.
       FD  INVOICE-OUT.
       01  OUT-REC.
           05  OUT-ITEM        PIC X(8).
           05  FILLER          PIC X.
           05  OUT-NET         PIC ZZZ,ZZ9.99.
           05  FILLER          PIC X.
           05  OUT-VAT         PIC ZZ,ZZ9.99.
           05  FILLER          PIC X.
           05  OUT-GROSS       PIC ZZZ,ZZ9.99-.
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE "N".
           88  END-OF-FILE     VALUE "Y".
       01  WS-NET              PIC S9(7)V99.
       01  WS-DISCOUNT         PIC SV999.
       01  WS-VAT              PIC S9(7)V99.
       01  WS-RATE             PIC V999.
       01  WS-TOTAL            PIC S9(9)V99 VALUE 0.
       01  WS-COUNT            PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT LINES-IN OUTPUT INVOICE-OUT
           PERFORM UNTIL END-OF-FILE
               READ LINES-IN
                   AT END SET END-OF-FILE TO TRUE
                   NOT AT END PERFORM PRICE-LINE
               END-READ
           END-PERFORM
           MOVE SPACES TO OUT-REC
           MOVE "TOTAL" TO OUT-ITEM
           MOVE WS-TOTAL TO OUT-GROSS
           WRITE OUT-REC
           DISPLAY "LINES PRICED: " WS-COUNT
           CLOSE LINES-IN INVOICE-OUT
           STOP RUN.
       PRICE-LINE.
           ADD 1 TO WS-COUNT
           EVALUATE TRUE
               WHEN IN-QTY >= 100  MOVE .150 TO WS-DISCOUNT
               WHEN IN-QTY >= 20   MOVE .050 TO WS-DISCOUNT
               WHEN OTHER          MOVE 0    TO WS-DISCOUNT
           END-EVALUATE
           COMPUTE WS-NET ROUNDED =
               IN-QTY * IN-PRICE * (1 - WS-DISCOUNT)
           EVALUATE IN-CLASS
               WHEN "F"   MOVE .050 TO WS-RATE
               WHEN "B"   MOVE .000 TO WS-RATE
               WHEN OTHER MOVE .200 TO WS-RATE
           END-EVALUATE
           COMPUTE WS-VAT ROUNDED = WS-NET * WS-RATE
           ADD WS-NET WS-VAT TO WS-TOTAL
           MOVE SPACES TO OUT-REC
           MOVE IN-ITEM TO OUT-ITEM
           MOVE WS-NET TO OUT-NET
           MOVE WS-VAT TO OUT-VAT
           COMPUTE OUT-GROSS = WS-NET + WS-VAT
           WRITE OUT-REC.
