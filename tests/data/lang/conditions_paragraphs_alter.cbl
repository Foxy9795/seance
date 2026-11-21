       IDENTIFICATION DIVISION.
       PROGRAM-ID. FEAT1.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           CURRENCY SIGN IS "W".
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  REC-A.
           05 STATUS-A PIC X VALUE "Y".
              88 OK VALUE "Y" FALSE "N".
              88 BAD VALUE "N".
       01  REC-B.
           05 STATUS-B PIC X VALUE "N".
              88 OK VALUE "Y" FALSE "N".
       01  TAB.
           05 ENT PIC 9(3) OCCURS 4 TIMES INDEXED IX1.
       01  NUM PIC 9(3) VALUE 7.
       01  AE1 PIC XXBXX/XX.
       01  AE2 PIC X0X0X.
       01  ED1 PIC WWW,WW9.99.
       01  ED2 PIC -9,9.9/9.
       01  ED3 PIC W9,9B9.9+.
       01  ED4 PIC ZZZPP.
       01  ED5 PIC .9/9,9,9.
       01  BACK PIC S9(6)V99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF OK OF REC-A DISPLAY "A OK" ELSE DISPLAY "A NOT OK".
           IF OK IN STATUS-B DISPLAY "B OK" ELSE DISPLAY "B NOT OK".
           SET OK OF REC-B BAD TO TRUE.
           DISPLAY STATUS-A STATUS-B.
           SET OK OF REC-A TO FALSE.
           DISPLAY STATUS-A.
           SET IX1 TO 3.
           MOVE 25 TO ENT (IX1).
           MULTIPLY NUM BY ENT (IX1).
           DISPLAY ENT (3).
           MOVE "ABCDEFGH" TO AE1.
           MOVE "XYZ" TO AE2.
           DISPLAY "[" AE1 "][" AE2 "]".
           MOVE 1234.5 TO ED1.
           DISPLAY "[" ED1 "]".
           MOVE ED1 TO BACK.
           DISPLAY BACK.
           MOVE -12.34 TO ED2.
           MOVE -1234.5 TO ED3.
           MOVE 12345 TO ED4.
           MOVE 0.1234 TO ED5.
           DISPLAY "[" ED2 "][" ED3 "][" ED4 "][" ED5 "]".
           PERFORM DUP-PARA OF SEC-TWO.
           PERFORM SEC-ONE.
           PERFORM SEC-TWO.
           ALTER SWITCH-PARA TO PROCEED TO SECOND-WAY.
           GO TO SWITCH-PARA.
       SWITCH-PARA.
           GO TO FIRST-WAY.
       FIRST-WAY.
           DISPLAY "FIRST WAY".
           GO TO DONE-PARA.
       SECOND-WAY.
           DISPLAY "SECOND WAY".
       DONE-PARA.
           STOP RUN.
       SEC-ONE SECTION.
       DUP-PARA.
           DISPLAY "DUP IN ONE".
           PERFORM DUP-PARA2.
       DUP-PARA2.
           DISPLAY "DUP2 IN ONE".
       SEC-TWO SECTION.
       DUP-PARA.
           DISPLAY "DUP IN TWO".
       DUP-PARA2.
           DISPLAY "DUP2 IN TWO".
