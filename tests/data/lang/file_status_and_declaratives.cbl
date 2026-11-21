       IDENTIFICATION DIVISION.
       PROGRAM-ID. IOSTAT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO "F1.DAT" ORGANIZATION LINE SEQUENTIAL
               FILE STATUS IS FS1.
           SELECT F2 ASSIGN TO "F2.DAT" ORGANIZATION LINE SEQUENTIAL
               FILE STATUS IS FS2.
           SELECT F3 ASSIGN TO "NOPE.DAT" ORGANIZATION LINE SEQUENTIAL
               FILE STATUS IS FS3.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  R1 PIC X(10).
       FD  F2.
       01  R2 PIC X(10).
       FD  F3.
       01  R3 PIC X(10).
       WORKING-STORAGE SECTION.
       01  FS1 PIC XX.
       01  FS2 PIC XX.
       01  FS3 PIC XX.
       01  CNT PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       DECLARATIVES.
       F2-ERR SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON F2.
       F2-ERR-1.
           ADD 1 TO CNT.
           DISPLAY "DECL F2 " FS2.
       IN-ERR SECTION.
           USE AFTER ERROR PROCEDURE ON INPUT.
       IN-ERR-1.
           DISPLAY "DECL INPUT " FS1 " " FS3.
       END DECLARATIVES.
       MAIN SECTION.
       MAIN-PARA.
           WRITE R1 FROM "X".
           DISPLAY "W1 " FS1.
           CLOSE F1.
           DISPLAY "C1 " FS1.
           OPEN OUTPUT F1.
           WRITE R1 FROM "LINE1".
           OPEN OUTPUT F1.
           DISPLAY "O1 " FS1.
           CLOSE F1.
           OPEN INPUT F1.
           READ F1.
           DISPLAY "R1 " FS1 " " R1.
           READ F1.
           DISPLAY "R2 " FS1.
           READ F1.
           DISPLAY "R3 " FS1.
           CLOSE F1.
           WRITE R2 FROM "Y".
           DISPLAY "W2 " FS2 " " CNT.
           OPEN INPUT F3.
           DISPLAY "O3 " FS3.
           CLOSE F1 WITH NO REWIND.
           DISPLAY "C2 " FS1.
           STOP RUN.
