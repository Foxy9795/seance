      * DCLGEN for table ACCOUNTS
           EXEC SQL DECLARE ACCOUNTS TABLE
                   (ACCTNO     CHAR(6)       NOT NULL,
                    OWNER      CHAR(12)      NOT NULL,
                    BALANCE    DECIMAL(9,2)  NOT NULL,
                    CREDIT     DECIMAL(7,2),
                    STATUS     CHAR(8)       NOT NULL)
           END-EXEC.
       01  DCL-ACCOUNTS.
           10  ACCTNO          PIC X(6).
           10  OWNER           PIC X(12).
           10  BALANCE         PIC S9(7)V99 COMP-3.
           10  CREDIT          PIC S9(5)V99 COMP-3.
           10  ACCT-STATUS     PIC X(8).
