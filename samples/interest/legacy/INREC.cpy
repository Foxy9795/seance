*> Account master record, one per line.
01 IN-REC.
   05 IN-ACCT-ID   PIC X(8).
   05 IN-BALANCE   PIC S9(9)V99 SIGN LEADING SEPARATE.
   05 IN-RATE      PIC 9V9(4).
   05 IN-DAYS      PIC 9(3).
