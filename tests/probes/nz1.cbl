       IDENTIFICATION DIVISION.
       PROGRAM-ID. NZ1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC S9V99 VALUE 0.
       01 AR REDEFINES A PIC X(3).
       01 B PIC S9V99 VALUE 0.
       01 C PIC S9V99 VALUE 0.
       01 D PIC S9V99 SIGN TRAILING SEPARATE VALUE 0.
       01 E PIC S9V99 COMP-3 VALUE 0.
       01 X PIC S9V999 VALUE -0.001.
       PROCEDURE DIVISION.
           MOVE X TO A.
           DISPLAY "A=" A.
           COMPUTE B = X * 1.
           DISPLAY "B=" B.
           COMPUTE C = -0.001.
           DISPLAY "C=" C.
           MOVE X TO D.
           DISPLAY "D=" D.
           MOVE X TO E.
           DISPLAY "E=" E.
           DISPLAY "AR=" AR.
           MOVE -0 TO A.
           DISPLAY "A2=" A.
           SUBTRACT 1 FROM A.
           ADD 1 TO A.
           DISPLAY "A3=" A.
           MULTIPLY -1 BY A.
           DISPLAY "A4=" A.
           STOP RUN.
