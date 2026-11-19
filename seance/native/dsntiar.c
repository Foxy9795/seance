/* DSNTIAR: DB2's routine that turns the SQLCA into readable message lines. The same text as seance/sqlbridge.py.

   CALL 'DSNTIAR' USING SQLCA MESSAGE-AREA LINE-LENGTH
   MESSAGE-AREA: a halfword (COMP) length of the text area, then the text; LINE-LENGTH: S9(9) COMP.
*/
#include <stdio.h>
#include <string.h>

int DSNTIAR(unsigned char *ca, unsigned char *msg, unsigned char *lrecl) {
    int code; memcpy(&code, ca + 12, 4);
    int area = (msg[0] << 8) | msg[1];           /* COMP is big-endian */
    int width = (lrecl[0] << 24) | (lrecl[1] << 16) | (lrecl[2] << 8) | lrecl[3];
    if (width <= 0 || width > area) width = area;
    memset(msg + 2, ' ', area);
    char line[200];
    int n = snprintf(line, sizeof line, "DSNT408I SQLCODE = %d, SQLSTATE = %.5s", code, (char *)(ca + 131));
    if (n > width) n = width;
    memcpy(msg + 2, line, n);
    return 0;
}
