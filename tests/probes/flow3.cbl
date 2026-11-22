       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLOW3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I PIC 9 VALUE 0.
       01 J PIC 9 VALUE 0.
       01 X PIC 99 VALUE 15.
       01 CHOICE PIC 9 VALUE 1.
       01 F2 USAGE COMP-2.
       01 D1 PIC 9(5) VALUE 12345.
       01 TBL.
          05 ITEM-ENTRY OCCURS 5 TIMES INDEXED BY IX.
             10 K PIC X(2).
       01 WS-CTR PIC 99 VALUE 10.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 2
               AFTER J FROM 1 BY 1 UNTIL J > 3
               CONTINUE
           END-PERFORM.
           DISPLAY "I=" I " J=" J.
           EVALUATE X
               WHEN > 10 AND < 20 DISPLAY "RANGE MATCH"
               WHEN OTHER DISPLAY "OTHER"
           END-EVALUATE.
           COMPUTE F2 = 10.0 ** 310.
           MOVE F2 TO D1.
           DISPLAY "D1=" D1.
           MOVE "AA" TO K(1). MOVE "BB" TO K(2). MOVE "CC" TO K(3).
           MOVE "DD" TO K(4). MOVE "EE" TO K(5).
           SET IX TO 1.
           SEARCH ITEM-ENTRY VARYING WS-CTR
               AT END DISPLAY "NOT FOUND CTR=" WS-CTR
               WHEN K(IX) = "DD"
                   DISPLAY "FOUND IX=" IX " CTR=" WS-CTR
           END-SEARCH.
           PERFORM DO-CHOICE.
           DISPLAY "AFTER-PERFORM".
           STOP RUN.
       DO-CHOICE.
           IF CHOICE = 1 GO TO BR-A.
           GO TO BR-B.
       BR-A.
           DISPLAY "BR-A".
       BR-B.
           DISPLAY "BR-B".
