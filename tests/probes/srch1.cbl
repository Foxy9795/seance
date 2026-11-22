       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCH1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 INIT-A.
          05 FILLER PIC X(12) VALUE "1a2b2c2d3e4f".
       01 TBL-A REDEFINES INIT-A.
          05 EA OCCURS 6 TIMES ASCENDING KEY IS KA INDEXED BY IA.
             10 KA PIC 9.
             10 VA PIC X.
       01 INIT-D.
          05 FILLER PIC X(12) VALUE "9a8b8c7d3e1f".
       01 TBL-D REDEFINES INIT-D.
          05 ED OCCURS 6 TIMES DESCENDING KEY IS KD INDEXED BY ID1.
             10 KD PIC 9.
             10 VD PIC X.
       01 N PIC 9 VALUE 5.
       01 TBL-O.
          05 EOO OCCURS 1 TO 6 TIMES DEPENDING ON N
             ASCENDING KEY IS KO INDEXED BY IO.
             10 KO PIC 9.
             10 VO PIC X.
       01 W PIC 9.
       PROCEDURE DIVISION.
           MOVE "1a2b2c2d3e4f" TO TBL-O.
           MOVE 2 TO W.
           SEARCH ALL EA AT END DISPLAY "A NOT FOUND"
               WHEN KA (IA) = W DISPLAY "A IX=" IA " V=" VA (IA)
           END-SEARCH.
           MOVE 5 TO W.
           SEARCH ALL EA AT END DISPLAY "A NOT FOUND"
               WHEN KA (IA) = W DISPLAY "A IX=" IA
           END-SEARCH.
           MOVE 8 TO W.
           SEARCH ALL ED AT END DISPLAY "D NOT FOUND"
               WHEN KD (ID1) = W DISPLAY "D IX=" ID1 " V=" VD (ID1)
           END-SEARCH.
           MOVE 3 TO W.
           SEARCH ALL EOO AT END DISPLAY "O NOT FOUND"
               WHEN KO (IO) = W DISPLAY "O IX=" IO
           END-SEARCH.
           MOVE 4 TO W.
           SEARCH ALL EOO AT END DISPLAY "O NOT FOUND"
               WHEN W = KO (IO) DISPLAY "O IX=" IO
           END-SEARCH.
           EVALUATE TRUE
               WHEN TRUE DISPLAY "TRUE WHEN TRUE"
           END-EVALUATE.
           STOP RUN.
