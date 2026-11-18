# Spec: ADD_AMOUNTS (from `legacy/add_amounts/add_amounts.cbl`)

Purpose, from the source comment: This program accepts input and displays output

The program reads console input (ACCEPT CUST-NO-IN, AMT1-IN, AMT2-IN, AMT3-IN, MORE-DATA). Source format: fixed (columns 8-72).

## Behavior by paragraph


### 100-MAIN (line 23)

- L24: Repeats the steps below until MORE-DATA = 'NO '.
  - L25: Shows 'ENTER NAME (15 CHARACTERS)' on the console.
  - L26: (not summarized) `ACCEPT CUST-NO-IN`
  - L27: Shows 'ENTER AMOUNT OF FIRST PURCHASE (5 DIGITS)' on the console.
  - L28: (not summarized) `ACCEPT AMT1-IN`
  - L29: Shows 'ENTER AMOUNT OF SECOND PURCHASE (5 DIGITS)' on the console.
  - L30: (not summarized) `ACCEPT AMT2-IN`
  - L31: Shows 'ENTER AMOUNT OF THIRD PURCHASE (5 DIGITS)' on the console.
  - L32: (not summarized) `ACCEPT AMT3-IN`
  - L33: Copies CUST-NO-IN into CUST-NO-OUT.
  - L34: (not summarized) `ADD AMT1-IN  AMT2-IN  AMT3-IN`
    - L35: (not summarized) `GIVING TOTAL-OUT`
  - L36: Shows CUST-NO-OUT 'TOTAL AMOUNT = ' TOTAL-OUT on the console.
  - L37: Shows 'MORE INPUT DATA (YES/NO)?' on the console.
  - L38: (not summarized) `ACCEPT MORE-DATA`
  - L39: (not summarized) `INSPECT MORE-DATA CONVERTING 'noyes' to 'NOYES'`
- L41: Ends the program.

## Where values can silently change

- None detected.

## Needs human review

- line 26: `ACCEPT CUST-NO-IN` was not summarized
- line 28: `ACCEPT AMT1-IN` was not summarized
- line 30: `ACCEPT AMT2-IN` was not summarized
- line 32: `ACCEPT AMT3-IN` was not summarized
- line 34: `ADD AMT1-IN  AMT2-IN  AMT3-IN` was not summarized
- line 35: `GIVING TOTAL-OUT` was not summarized
- line 38: `ACCEPT MORE-DATA` was not summarized
- line 39: `INSPECT MORE-DATA CONVERTING 'noyes' to 'NOYES'` was not summarized
