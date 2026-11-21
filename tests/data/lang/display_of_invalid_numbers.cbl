       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISPPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  G1.
           05 G1X PIC X(6).
       01  N6    PIC 9(6).
       01  S6    PIC S9(6).
       01  X6    PIC X(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "123ABC" TO G1X. MOVE G1 TO N6 S6.
           MOVE N6 TO X6.
           DISPLAY "[" N6 "][" S6 "][" X6 "]".
           MOVE "ABCDEF" TO G1X. MOVE G1 TO N6 S6.
           DISPLAY "[" N6 "][" S6 "]".
           MOVE "1A2B3C" TO G1X. MOVE G1 TO N6 S6.
           DISPLAY "[" N6 "][" S6 "]".
           MOVE "12 4 6" TO G1X. MOVE G1 TO N6 S6.
           DISPLAY "[" N6 "][" S6 "]".
           MOVE "GHIJKL" TO G1X. MOVE G1 TO N6 S6.
           DISPLAY "[" N6 "][" S6 "]".
           MOVE "{}pqrs" TO G1X. MOVE G1 TO N6 S6.
           DISPLAY "[" N6 "][" S6 "]".
           STOP RUN.
