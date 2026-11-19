"""A small fixed-format program the tests add to the workspace."""

TEMPLATE = {
    "name": "discount",
    "cobol": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISCOUNT.
      * Order pricing: a percentage off the amount, rounded to cents.
      * A negative adjustment (a refund) keeps its sign.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDERS-IN  ASSIGN TO ORDERIN.
           SELECT ORDERS-OUT ASSIGN TO ORDEROUT.
       DATA DIVISION.
       FILE SECTION.
       FD  ORDERS-IN RECORDING MODE F.
       01  IN-REC.
           05  IN-ORDER-ID  PIC X(6).
           05  IN-AMOUNT    PIC S9(5)V99.
           05  IN-PCT       PIC 9(3)V99.
           05  FILLER       PIC X(4).
       FD  ORDERS-OUT RECORDING MODE F.
       01  OUT-REC.
           05  OUT-ORDER-ID  PIC X(6).
           05  OUT-DISCOUNT  PIC S9(5)V99.
           05  OUT-TOTAL     PIC S9(6)V99.
           05  OUT-SHOWN     PIC $$,$$$,$$9.99-.
       WORKING-STORAGE SECTION.
       01  WS-FLAGS.
           05  WS-EOF        PIC X VALUE 'N'.
               88  AT-EOF    VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ORDERS-IN OUTPUT ORDERS-OUT
           PERFORM UNTIL AT-EOF
               READ ORDERS-IN
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM PRICE-ORDER
               END-READ
           END-PERFORM
           CLOSE ORDERS-IN ORDERS-OUT
           STOP RUN.
       PRICE-ORDER.
           MOVE IN-ORDER-ID TO OUT-ORDER-ID
           COMPUTE OUT-DISCOUNT ROUNDED = IN-AMOUNT * IN-PCT / 100
           COMPUTE OUT-TOTAL = IN-AMOUNT - OUT-DISCOUNT
           MOVE OUT-TOTAL TO OUT-SHOWN
           WRITE OUT-REC.
""",
    "copybooks": [],
}
