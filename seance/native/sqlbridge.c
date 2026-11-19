/* SQLBRIDGE: embedded SQL for GnuCOBOL programs, on SQLite.

   Séance's SQL precompiler turns every EXEC SQL statement into plain COBOL that CALLs this module. The Python
   side has the same bridge in seance/sqlbridge.py; both follow the rules below, so a program's SQL behaves the
   same on both sides and the check compares the COBOL logic around it.

   CALL 'SQLBRIDGE' USING SQLCA OP CURSOR TEXT NPARAM PARAMS PNULLS NRES RESULTS RNULLS RLENS

   SQLCA   136 bytes, DB2 layout: SQLCODE at 12 (COMP-5), SQLERRD at 96 (6 x COMP-5), SQLSTATE at 131
   OP      X(8): EXEC, OPEN, OPENU (cursor FOR UPDATE: the last column is the rowid), FETCH, CLOSE, CURRENT,
           COMMIT, ROLLBACK, NOOP
   CURSOR  X(30)    TEXT X(4000), statement with ? markers    NPARAM 9(4)   PARAMS 64 x X(256)   PNULLS X(64)
   NRES    9(4)     RESULTS 64 x X(256)   RNULLS X(64)   RLENS 64 x 9(4)

   Values travel as text: parameters lose trailing blanks; results are SQLite's own text form of the value.
   The database is the file named by SEANCE_SQLDB. Work runs in one transaction, committed at COMMIT and when
   the program ends normally.
*/
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
extern int sqlite3_initialize(void);
extern int sqlite3_open(const char *, sqlite3 **);
extern int sqlite3_prepare_v2(sqlite3 *, const char *, int, sqlite3_stmt **, const char **);
extern int sqlite3_bind_text(sqlite3_stmt *, int, const char *, int, void (*)(void *));
extern int sqlite3_bind_null(sqlite3_stmt *, int);
extern int sqlite3_bind_int64(sqlite3_stmt *, int, long long);
extern int sqlite3_step(sqlite3_stmt *);
extern int sqlite3_column_count(sqlite3_stmt *);
extern int sqlite3_column_type(sqlite3_stmt *, int);
extern const unsigned char *sqlite3_column_text(sqlite3_stmt *, int);
extern long long sqlite3_column_int64(sqlite3_stmt *, int);
extern int sqlite3_finalize(sqlite3_stmt *);
extern int sqlite3_changes(sqlite3 *);
extern int sqlite3_extended_errcode(sqlite3 *);
extern int sqlite3_exec(sqlite3 *, const char *, void *, void *, char **);
extern int sqlite3_close(sqlite3 *);
extern int sqlite3_stmt_readonly(sqlite3_stmt *);
#define SQLITE_ROW 100
#define SQLITE_DONE 101
#define SQLITE_NULL 5
#define SQLITE_TRANSIENT ((void (*)(void *)) - 1)

#define PSIZE 256
#define MAXP 64
#define MAXC 16

static sqlite3 *db = NULL;
static struct { char name[31]; sqlite3_stmt *st; int update; long long rowid; } cursors[MAXC];

static void finish(void) {
    if (db) { sqlite3_exec(db, "COMMIT", 0, 0, 0); sqlite3_close(db); db = NULL; }
}

static int connect(void) {
    if (db) return 0;
    sqlite3_initialize();  /* Python's build of the library does not initialize itself */
    const char *path = getenv("SEANCE_SQLDB");
    if (!path || sqlite3_open(path, &db) != 0) return -1;
    sqlite3_exec(db, "BEGIN", 0, 0, 0);
    atexit(finish);
    return 0;
}

static void put32(unsigned char *p, int v) { memcpy(p, &v, 4); }

static void set_code(unsigned char *ca, int code, const char *state, int rows) {
    memcpy(ca, "SQLCA   ", 8);
    put32(ca + 8, 136);
    put32(ca + 12, code);
    memset(ca + 16, 0, 2);
    memset(ca + 18, ' ', 70);
    memset(ca + 88, ' ', 8);
    memset(ca + 96, 0, 24);
    put32(ca + 104, rows);  /* SQLERRD(3) */
    memset(ca + 120, ' ', 11);
    memcpy(ca + 131, state, 5);
}

/* the mapping both bridges use: SQLite result -> DB2 SQLCODE / SQLSTATE */
static void set_error(unsigned char *ca, int rc) {
    int primary = rc & 0xff;
    if (rc == 1555 || rc == 2067) { set_code(ca, -803, "23505", 0); return; }      /* PRIMARYKEY, UNIQUE */
    if (rc == 1299) { set_code(ca, -407, "23502", 0); return; }                    /* NOTNULL */
    if (primary == 19) { set_code(ca, -545, "23513", 0); return; }                  /* other constraint */
    if (primary == 1) { set_code(ca, -104, "42601", 0); return; }                   /* SQL error, syntax */
    set_code(ca, -901, "58004", 0);
}

static int num(const unsigned char *p, int n) { int v = 0; for (int i = 0; i < n; i++) if (p[i] >= '0' && p[i] <= '9') v = v * 10 + p[i] - '0'; return v; }

static char *latin1_to_utf8(const unsigned char *s, int n) {
    char *out = malloc(n * 2 + 1); int j = 0;
    for (int i = 0; i < n; i++) { unsigned c = s[i]; if (c < 0x80) out[j++] = (char)c; else { out[j++] = (char)(0xC0 | (c >> 6)); out[j++] = (char)(0x80 | (c & 0x3F)); } }
    out[j] = 0; return out;
}

static int utf8_to_latin1(const unsigned char *s, unsigned char *out, int cap) {
    int j = 0;
    for (int i = 0; s[i] && j < cap; i++) {
        unsigned c = s[i];
        if (c < 0x80) out[j++] = (unsigned char)c;
        else if ((c & 0xE0) == 0xC0 && s[i + 1]) { out[j++] = (unsigned char)(((c & 0x1F) << 6) | (s[i + 1] & 0x3F)); i++; }
        else { out[j++] = '?'; while ((s[i + 1] & 0xC0) == 0x80) i++; }
    }
    return j;
}

static sqlite3_stmt *prepare(unsigned char *ca, unsigned char *text, int nparam, unsigned char *params, unsigned char *pnulls, long long extra, int use_extra) {
    int len = 4000; while (len > 0 && text[len - 1] == ' ') len--;
    char *sql = latin1_to_utf8(text, len);
    sqlite3_stmt *st = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &st, NULL);
    free(sql);
    if (rc != 0) { set_error(ca, sqlite3_extended_errcode(db)); return NULL; }
    for (int i = 0; i < nparam && i < MAXP; i++) {
        if (pnulls[i] == 'Y') { sqlite3_bind_null(st, i + 1); continue; }
        unsigned char *p = params + i * PSIZE; int n = PSIZE;
        while (n > 0 && p[n - 1] == ' ') n--;
        int lead = 0; while (lead < n && p[lead] == ' ') lead++;   /* edited numbers come right-aligned */
        char *v = latin1_to_utf8(p + lead, n - lead);
        sqlite3_bind_text(st, i + 1, v, -1, SQLITE_TRANSIENT);
        free(v);
    }
    if (use_extra) sqlite3_bind_int64(st, nparam + 1, extra);
    return st;
}

static void deliver(sqlite3_stmt *st, int nres, int skip_last, unsigned char *results, unsigned char *rnulls, unsigned char *rlens) {
    int cols = sqlite3_column_count(st) - (skip_last ? 1 : 0);
    for (int i = 0; i < nres && i < MAXP; i++) {
        unsigned char *r = results + i * PSIZE;
        memset(r, ' ', PSIZE);
        int n = 0;
        if (i < cols && sqlite3_column_type(st, i) != SQLITE_NULL) {
            rnulls[i] = 'N';
            n = utf8_to_latin1(sqlite3_column_text(st, i), r, PSIZE);
        } else rnulls[i] = 'Y';
        char buf[5]; snprintf(buf, 5, "%04d", n); memcpy(rlens + i * 4, buf, 4);
    }
}

static int find(const unsigned char *name) {
    for (int i = 0; i < MAXC; i++) if (cursors[i].st && memcmp(cursors[i].name, name, 30) == 0) return i;
    return -1;
}

int SQLBRIDGE(unsigned char *ca, unsigned char *op, unsigned char *cursor, unsigned char *text, unsigned char *np,
              unsigned char *params, unsigned char *pnulls, unsigned char *nr, unsigned char *results,
              unsigned char *rnulls, unsigned char *rlens) {
    int nparam = num(np, 4), nres = num(nr, 4);
    if (connect() != 0) { set_code(ca, -924, "58031", 0); return 0; }
    set_code(ca, 0, "00000", 0);
    if (!memcmp(op, "NOOP", 4)) return 0;
    if (!memcmp(op, "COMMIT", 6)) { sqlite3_exec(db, "COMMIT", 0, 0, 0); sqlite3_exec(db, "BEGIN", 0, 0, 0); return 0; }
    if (!memcmp(op, "ROLLBACK", 8)) { sqlite3_exec(db, "ROLLBACK", 0, 0, 0); sqlite3_exec(db, "BEGIN", 0, 0, 0); return 0; }
    if (!memcmp(op, "OPEN", 4)) {
        if (find(cursor) >= 0) { set_code(ca, -502, "24502", 0); return 0; }
        sqlite3_stmt *st = prepare(ca, text, nparam, params, pnulls, 0, 0);
        if (!st) return 0;
        for (int i = 0; i < MAXC; i++) if (!cursors[i].st) {
            memcpy(cursors[i].name, cursor, 30); cursors[i].st = st; cursors[i].update = op[4] == 'U'; cursors[i].rowid = 0; return 0;
        }
        sqlite3_finalize(st); set_code(ca, -904, "57011", 0); return 0;
    }
    if (!memcmp(op, "FETCH", 5)) {
        int c = find(cursor);
        if (c < 0) { set_code(ca, -501, "24501", 0); return 0; }
        int rc = sqlite3_step(cursors[c].st);
        if (rc == SQLITE_ROW) {
            int cols = sqlite3_column_count(cursors[c].st);
            if (cursors[c].update) cursors[c].rowid = sqlite3_column_int64(cursors[c].st, cols - 1);
            deliver(cursors[c].st, nres, cursors[c].update, results, rnulls, rlens);
            set_code(ca, 0, "00000", 1);
        } else if (rc == SQLITE_DONE) set_code(ca, 100, "02000", 0);
        else set_error(ca, sqlite3_extended_errcode(db));
        return 0;
    }
    if (!memcmp(op, "CLOSE", 5)) {
        int c = find(cursor);
        if (c < 0) { set_code(ca, -501, "24501", 0); return 0; }
        sqlite3_finalize(cursors[c].st); cursors[c].st = NULL; return 0;
    }
    /* EXEC, or CURRENT (UPDATE/DELETE ... WHERE CURRENT OF cursor: the cursor's row id is the last parameter) */
    long long rowid = 0; int current = !memcmp(op, "CURRENT", 7);
    if (current) {
        int c = find(cursor);
        if (c < 0) { set_code(ca, -501, "24501", 0); return 0; }
        rowid = cursors[c].rowid;
    }
    sqlite3_stmt *st = prepare(ca, text, nparam, params, pnulls, rowid, current);
    if (!st) return 0;
    /* the same rule as the Python bridge: a statement that starts with SELECT, WITH or VALUES returns rows */
    int readonly = !memcmp(text, "SELECT", 6) || !memcmp(text, "WITH", 4) || !memcmp(text, "VALUES", 6);
    int rc = sqlite3_step(st);
    if (readonly) {  /* SELECT ... INTO */
        if (rc == SQLITE_ROW) {
            deliver(st, nres, 0, results, rnulls, rlens);
            rc = sqlite3_step(st);
            if (rc == SQLITE_ROW) set_code(ca, -811, "21000", 0); else set_code(ca, 0, "00000", 1);
        } else if (rc == SQLITE_DONE) set_code(ca, 100, "02000", 0);
        else set_error(ca, sqlite3_extended_errcode(db));
    } else if (rc == SQLITE_DONE) {
        int rows = sqlite3_changes(db);
        int searched = !memcmp(text, "UPDATE", 6) || !memcmp(text, "DELETE", 6);
        if (rows == 0 && searched) set_code(ca, 100, "02000", 0); else set_code(ca, 0, "00000", rows);
    } else set_error(ca, sqlite3_extended_errcode(db));
    sqlite3_finalize(st);
    return 0;
}
