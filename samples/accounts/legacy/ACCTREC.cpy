      * Account master record (fixed length, no line breaks).
       01  ACCT-REC.
           05  ACCT-NO          PIC X(8).
           05  ACCT-BALANCE     PIC S9(7)V99.
           05  ACCT-LIMIT       PIC 9(7)V99.
           05  ACCT-RATE        PIC V9(4).
           05  ACCT-TYPE        PIC X.
               88  SAVINGS      VALUE 'S'.
               88  CHECKING     VALUE 'C'.
           05  ACCT-MONTHS      PIC 99.
           05  FILLER           PIC X(5).
