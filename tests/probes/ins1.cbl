       IDENTIFICATION DIVISION.
       PROGRAM-ID. INS1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 S1 PIC X(2) VALUE "AB".
       01 S2 PIC X(2) VALUE "AB".
       01 S3 PIC X(3) VALUE "ABC".
       01 S4 PIC X(8) VALUE "SUSTUTSU".
       01 S5 PIC X(6) VALUE "AABBAA".
       01 C1 PIC 99 VALUE 0.
       01 C2 PIC 99 VALUE 0.
       01 C3 PIC 99 VALUE 0.
       PROCEDURE DIVISION.
           INSPECT S1 REPLACING ALL "A" BY "B" ALL "B" BY "C".
           DISPLAY "S1=" S1.
           INSPECT S2 TALLYING C1 FOR ALL "A" C2 FOR CHARACTERS.
           DISPLAY "C1=" C1 " C2=" C2.
           INSPECT S3 CONVERTING "ZZC" TO "XYC".
           DISPLAY "S3=" S3.
           INSPECT S3 CONVERTING "AAB" TO "XYZ".
           DISPLAY "S3=" S3.
           INSPECT S4 TALLYING C3 FOR LEADING "S" AFTER "U"
              "T" AFTER "U".
           DISPLAY "C3=" C3.
           MOVE 0 TO C1 C2.
           INSPECT S5 TALLYING C1 FOR ALL "AA"
              REPLACING FIRST "B" BY "X" ALL "A" BY "Z".
           DISPLAY "S5=" S5 " C1=" C1.
           INSPECT S5 REPLACING LEADING "Z" BY "Q"
              CHARACTERS BY "-" BEFORE "B".
           DISPLAY "S5=" S5.
           STOP RUN.
