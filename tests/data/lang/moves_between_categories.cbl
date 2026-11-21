       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  A5    PIC X(5) VALUE "12345".
       01  A6    PIC X(6) VALUE "12AB5 ".
       01  E1    PIC $ZZ,ZZZ.99.
       01  E2    PIC ZZZ9.99-.
       01  E3    PIC ***9.9.
       01  G1.
           05 FILLER PIC X(6) VALUE "123ABC".
       01  N2    PIC 99.
       01  N6    PIC 9(6).
       01  AN    PIC X(12) VALUE "012345678912".
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE A5 TO E1. DISPLAY "[" E1 "]".
           MOVE A6 TO E1. DISPLAY "[" E1 "]".
           MOVE -12.5 TO E2. MOVE E2 TO E3.
           DISPLAY "[" E2 "][" E3 "]".
           MOVE G1 TO N2. DISPLAY "[" N2 "]".
           MOVE G1 TO N6. DISPLAY "[" N6 "]".
           IF AN = 012345678912
              DISPLAY "EQUAL"
           ELSE
              DISPLAY "NOT EQUAL".
           IF AN = 12345678912
              DISPLAY "EQUAL2"
           ELSE
              DISPLAY "NOT EQUAL2".
           PERFORM PB THRU PA.
           DISPLAY "BACK".
           STOP RUN.
       PA.
           DISPLAY "IN PA".
       PB.
           DISPLAY "IN PB".
           GO TO PA.
