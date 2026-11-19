      * Symbolic map for mapset CUSTSET, map CUSTM (as BMS generates it)
       01  CUSTMI.
           05  FILLER         PIC X(12).
           05  CUSTNOI        PIC X(6).
           05  ACTIONI        PIC X.
           05  AMOUNTI        PIC 9(5)V99.
       01  CUSTMO REDEFINES CUSTMI.
           05  FILLER         PIC X(12).
           05  CUSTNOO        PIC X(6).
           05  ACTIONO        PIC X.
           05  AMOUNTO        PIC 9(5)V99.
       01  CUSTMSG.
           05  MSG-CUSTNO     PIC X(6).
           05  FILLER         PIC X VALUE SPACE.
           05  MSG-NAME       PIC X(20).
           05  FILLER         PIC X VALUE SPACE.
           05  MSG-BALANCE    PIC -(6)9.99.
           05  FILLER         PIC X VALUE SPACE.
           05  MSG-TEXT       PIC X(30).
