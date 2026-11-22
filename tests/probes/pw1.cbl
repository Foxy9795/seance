       IDENTIFICATION DIVISION.
       PROGRAM-ID. PW1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC S9(5)V99 VALUE 0.
       01 B PIC S9(5)V99 VALUE 0.
       01 C PIC S9(3)V9(4) VALUE 2.
       01 N PIC S9 VALUE -1.
       PROCEDURE DIVISION.
	   COMPUTE A = 0 ** N
	   COMPUTE B = 0 ** 0
       DISPLAY "A=" A " B=" B
       COMPUTE A = C ** 3
       COMPUTE B = 2 ** N
       DISPLAY "A=" A " B=" B
       STOP RUN.
