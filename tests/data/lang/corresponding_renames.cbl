       IDENTIFICATION DIVISION.
       PROGRAM-ID. FEAT4.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  REC-A.
           05 NAME-F  PIC X(5) VALUE "ALICE".
           05 AMT     PIC 9(3)V99 VALUE 12.50.
           05 QTY     PIC 99 VALUE 3.
           05 SUB-G.
              10 CODE-F PIC XX VALUE "AB".
              10 RATE   PIC 9V9 VALUE 1.5.
           05 FILLER  PIC X VALUE "*".
           05 ONLY-A  PIC X VALUE "Q".
       01  REC-B.
           05 QTY     PIC 9(3) VALUE 100.
           05 AMT     PIC 9(4)V99 VALUE 1000.
           05 NAME-F  PIC X(8).
           05 SUB-G.
              10 RATE   PIC 99V9 VALUE 10.
              10 CODE-F PIC X(4).
           05 ONLY-B  PIC X VALUE "R".
       01  REC-C.
           05 C1 PIC XX VALUE "C1".
           05 C2 PIC 999 VALUE 42.
           05 C3 PIC X(3) VALUE "C3!".
       66  C-ALL RENAMES C1 THRU C3.
       66  C-NUM RENAMES C2.
       01  T-VAL PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD CORRESPONDING REC-A TO REC-B.
           DISPLAY QTY OF REC-B " " AMT OF REC-B " " RATE OF REC-B.
           SUBTRACT CORR REC-A FROM REC-B.
           DISPLAY QTY OF REC-B " " AMT OF REC-B " " RATE OF REC-B.
           MOVE CORRESPONDING REC-A TO REC-B.
           DISPLAY "[" REC-B "]".
           MOVE C-ALL TO T-VAL.
           DISPLAY "[" T-VAL "]".
           ADD 1 TO C-NUM.
           DISPLAY C2 " " C-NUM.
           STOP RUN.
