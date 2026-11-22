       IDENTIFICATION DIVISION.
       PROGRAM-ID. MATH2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 F1 USAGE COMP-1.
       01 F2 USAGE COMP-2.
       01 D1 PIC 9(5).
       01 G1.
          05 X1 PIC X.
          05 X2 PIC X.
       01 G1-P REDEFINES G1.
          05 P2 PIC S9(2) COMP-3.
       01 D2 PIC S9(5).
       01 U-CMP5 PIC 9(4) COMP-5 VALUE 1234.
       01 W PIC X(5) VALUE "ABCDE".
       01 Z PIC X(5) VALUE "ABCAB".
       PROCEDURE DIVISION.
           MOVE -1.5E+05 TO F1.
           DISPLAY "F1=" F1.
           COMPUTE F1 = 10.0 ** 40
               ON SIZE ERROR DISPLAY "OVERFLOW 1"
               NOT ON SIZE ERROR DISPLAY "NO OVERFLOW 1"
           END-COMPUTE.
           COMPUTE F2 = 10.0 ** 310
               ON SIZE ERROR DISPLAY "OVERFLOW 2"
               NOT ON SIZE ERROR DISPLAY "NO OVERFLOW 2"
           END-COMPUTE.
           MOVE X'14' TO X1.
           MOVE X'2C' TO X2.
           MOVE P2 TO D2.
           DISPLAY "MOVE D2=" D2.
           ADD 1 TO P2 GIVING D2.
           DISPLAY "ADD D2=" D2.
           COMPUTE U-CMP5 = -5
               ON SIZE ERROR DISPLAY "SIZE ERROR COMP-5"
               NOT ON SIZE ERROR DISPLAY "NO SIZE ERROR: " U-CMP5
           END-COMPUTE.
           INSPECT W CONVERTING "ABC" TO ZEROES.
           DISPLAY "W=" W.
           INSPECT Z REPLACING ALL "AB" BY ZEROES.
           DISPLAY "Z=" Z.
           STOP RUN.
