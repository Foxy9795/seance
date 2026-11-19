       IDENTIFICATION DIVISION.
       PROGRAM-ID. IDXDEMO.
      * Applies transactions to an indexed customer master (VSAM KSDS
      * style): add, change, delete, then lists by region.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER ASSIGN TO CUSTMAST
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS M-ID
               ALTERNATE RECORD KEY IS M-REGION WITH DUPLICATES
               FILE STATUS IS WS-FS.
           SELECT TRANS ASSIGN TO TRANSIN
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-OUT ASSIGN TO RPTOUT
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  MASTER.
       01  M-REC.
           05  M-ID       PIC X(5).
           05  M-REGION   PIC X(2).
           05  M-BALANCE  PIC S9(5)V99 COMP-3.
           05  M-NAME     PIC X(10).
       FD  TRANS.
       01  T-REC.
           05  T-ACTION   PIC X.
           05  T-ID       PIC X(5).
           05  T-REGION   PIC X(2).
           05  T-AMOUNT   PIC S9(5)V99 SIGN LEADING SEPARATE.
           05  T-NAME     PIC X(10).
       FD  REPORT-OUT.
       01  RPT-LINE       PIC X(60).
       WORKING-STORAGE SECTION.
       01  WS-FS          PIC XX.
       01  WS-EOF         PIC X VALUE 'N'.
       01  WS-SHOWN       PIC -(5)9.99.
       01  WS-COUNTS.
           05  WS-ADDED   PIC 9(3) VALUE 0.
           05  WS-CHANGED PIC 9(3) VALUE 0.
           05  WS-DELETED PIC 9(3) VALUE 0.
           05  WS-REJECTS PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN I-O MASTER
           IF WS-FS NOT = '00'
               DISPLAY 'OPEN FAILED ' WS-FS
               STOP RUN
           END-IF
           OPEN INPUT TRANS OUTPUT REPORT-OUT
           PERFORM UNTIL WS-EOF = 'Y'
               READ TRANS
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM APPLY-ONE
               END-READ
           END-PERFORM
           PERFORM LIST-BY-REGION
           DISPLAY 'ADDED ' WS-ADDED ' CHANGED ' WS-CHANGED
                   ' DELETED ' WS-DELETED ' REJECTED ' WS-REJECTS
           CLOSE MASTER TRANS REPORT-OUT
           STOP RUN.
       APPLY-ONE.
           MOVE T-ID TO M-ID
           EVALUATE T-ACTION
               WHEN 'A'
                   MOVE T-REGION TO M-REGION
                   MOVE T-AMOUNT TO M-BALANCE
                   MOVE T-NAME TO M-NAME
                   WRITE M-REC
                       INVALID KEY ADD 1 TO WS-REJECTS
                       NOT INVALID KEY ADD 1 TO WS-ADDED
                   END-WRITE
               WHEN 'C'
                   READ MASTER
                       INVALID KEY ADD 1 TO WS-REJECTS
                       NOT INVALID KEY
                           ADD T-AMOUNT TO M-BALANCE
                           REWRITE M-REC
                           ADD 1 TO WS-CHANGED
                   END-READ
               WHEN 'D'
                   DELETE MASTER RECORD
                       INVALID KEY ADD 1 TO WS-REJECTS
                       NOT INVALID KEY ADD 1 TO WS-DELETED
                   END-DELETE
               WHEN OTHER
                   ADD 1 TO WS-REJECTS
           END-EVALUATE.
       LIST-BY-REGION.
           MOVE LOW-VALUES TO M-REGION
           START MASTER KEY IS NOT LESS THAN M-REGION
               INVALID KEY MOVE 'Y' TO WS-EOF
               NOT INVALID KEY MOVE 'N' TO WS-EOF
           END-START
           PERFORM UNTIL WS-EOF = 'Y'
               READ MASTER NEXT RECORD
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       MOVE M-BALANCE TO WS-SHOWN
                       MOVE SPACES TO RPT-LINE
                       STRING M-REGION ' ' M-ID ' ' M-NAME ' ' WS-SHOWN
                           ' ' WS-FS DELIMITED BY SIZE INTO RPT-LINE
                       WRITE RPT-LINE
               END-READ
           END-PERFORM.
