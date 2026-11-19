       IDENTIFICATION DIVISION.
       PROGRAM-ID. RELDEMO.
      * Seat bookings in a relative file: slot number = seat number.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEATS ASSIGN TO SEATFILE
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS DYNAMIC
               RELATIVE KEY IS WS-SEAT
               FILE STATUS IS WS-FS.
           SELECT REQS ASSIGN TO REQFILE
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  SEATS.
       01  SEAT-REC.
           05  S-NAME     PIC X(8).
           05  S-PAID     PIC 9(3)V99.
       FD  REQS.
       01  REQ-REC.
           05  R-ACTION   PIC X.
           05  R-SEAT     PIC 9(3).
           05  R-NAME     PIC X(8).
           05  R-PAID     PIC 9(3)V99.
       WORKING-STORAGE SECTION.
       01  WS-SEAT        PIC 9(4).
       01  WS-FS          PIC XX.
       01  WS-EOF         PIC X VALUE 'N'.
       01  WS-TAKEN       PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN I-O SEATS
           OPEN INPUT REQS
           PERFORM UNTIL WS-EOF = 'Y'
               READ REQS
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM ONE-REQUEST
               END-READ
           END-PERFORM
           MOVE 1 TO WS-SEAT
           MOVE 'N' TO WS-EOF
           START SEATS KEY IS >= WS-SEAT
               INVALID KEY MOVE 'Y' TO WS-EOF
           END-START
           PERFORM UNTIL WS-EOF = 'Y'
               READ SEATS NEXT
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-TAKEN
                       DISPLAY 'SEAT ' WS-SEAT ' ' S-NAME ' ' S-PAID
               END-READ
           END-PERFORM
           DISPLAY 'TAKEN ' WS-TAKEN
           CLOSE SEATS REQS
           STOP RUN.
       ONE-REQUEST.
           MOVE R-SEAT TO WS-SEAT
           IF R-ACTION = 'B'
               MOVE R-NAME TO S-NAME
               MOVE R-PAID TO S-PAID
               WRITE SEAT-REC
                   INVALID KEY DISPLAY 'TAKEN OR BAD ' R-SEAT ' ' WS-FS
               END-WRITE
           ELSE
               DELETE SEATS
                   INVALID KEY DISPLAY 'NOT BOOKED ' R-SEAT ' ' WS-FS
               END-DELETE
           END-IF.
