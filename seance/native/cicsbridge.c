/* CICSBRIDGE: the CICS commands of a precompiled program, on SQLite. Same rules as seance/cicsbridge.py.

   CALL 'CICSBRIDGE' USING DFHEIBLK OP NAME KEYLEN KEY DATALEN DATA ITEM
   The database (SEANCE_CICSDB) holds files, tsq, term_in, term_out and control; see the Python module.
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
extern int sqlite3_bind_blob(sqlite3_stmt *, int, const void *, int, void (*)(void *));
extern int sqlite3_bind_int(sqlite3_stmt *, int, int);
extern int sqlite3_step(sqlite3_stmt *);
extern const void *sqlite3_column_blob(sqlite3_stmt *, int);
extern int sqlite3_column_bytes(sqlite3_stmt *, int);
extern int sqlite3_column_int(sqlite3_stmt *, int);
extern int sqlite3_column_type(sqlite3_stmt *, int);
extern int sqlite3_finalize(sqlite3_stmt *);
extern int sqlite3_changes(sqlite3 *);
extern int sqlite3_close(sqlite3 *);
#define SQLITE_ROW 100
#define SQLITE_DONE 101
#define SQLITE_NULL 5
#define T ((void (*)(void *)) - 1)

static sqlite3 *db = NULL;
static struct { char file[9]; unsigned char key[256]; int len; int has; } last[16];
static struct { char file[9]; unsigned char pos[256]; int len; int incl; int has; } brw[16];
static struct { char q[9]; int pos; } qpos[16];

static void done(void) { if (db) { sqlite3_close(db); db = NULL; } }

static int num(const unsigned char *p) { int v = 0; for (int i = 0; i < 5; i++) if (p[i] >= '0' && p[i] <= '9') v = v * 10 + p[i] - '0'; return v; }
static void put_num(unsigned char *p, int v) { char b[6]; snprintf(b, 6, "%05d", v % 100000); memcpy(p, b, 5); }
static void resp(unsigned char *eib, int code) {
    eib[76] = (code >> 24) & 255; eib[77] = (code >> 16) & 255; eib[78] = (code >> 8) & 255; eib[79] = code & 255;
    memset(eib + 80, 0, 4);
}
static void trim(const unsigned char *src, int n, char *out) { while (n > 0 && src[n - 1] == ' ') n--; int s = 0; while (s < n && src[s] == ' ') s++; memcpy(out, src + s, n - s); out[n - s] = 0; }

static sqlite3_stmt *q(const char *sql) { sqlite3_stmt *st = NULL; sqlite3_prepare_v2(db, sql, -1, &st, NULL); return st; }

static int get_ctl(const char *name, unsigned char *out, int cap) {
    sqlite3_stmt *st = q("SELECT value FROM control WHERE name = ?");
    sqlite3_bind_text(st, 1, name, -1, T);
    int n = -1;
    if (sqlite3_step(st) == SQLITE_ROW && sqlite3_column_type(st, 0) != SQLITE_NULL) {
        n = sqlite3_column_bytes(st, 0); if (n > cap) n = cap;
        memcpy(out, sqlite3_column_blob(st, 0), n);
    }
    sqlite3_finalize(st);
    return n;
}
static void set_ctl(const char *name, const void *v, int n) {
    sqlite3_stmt *st = q("INSERT OR REPLACE INTO control VALUES (?, ?)");
    sqlite3_bind_text(st, 1, name, -1, T); sqlite3_bind_blob(st, 2, v, n, T);
    sqlite3_step(st); sqlite3_finalize(st);
}

static int slot(void *arr, int size, int count, const char *name) {
    for (int i = 0; i < count; i++) { char *p = (char *)arr + i * size; if (strcmp(p, name) == 0) return i; }
    for (int i = 0; i < count; i++) { char *p = (char *)arr + i * size; if (!p[0]) { strcpy(p, name); return i; } }
    return 0;
}

static void copy_out(unsigned char *data, int dl, const void *src, int n) { int m = n < dl ? n : dl; memcpy(data, src, m); }

int CICSBRIDGE(unsigned char *eib, unsigned char *opf, unsigned char *namef, unsigned char *keylen, unsigned char *key,
               unsigned char *datalen, unsigned char *data, unsigned char *item) {
    if (!db) {
        sqlite3_initialize();
        const char *path = getenv("SEANCE_CICSDB");
        if (!path || sqlite3_open(path, &db) != 0) { resp(eib, 1); return 0; }
        atexit(done);
    }
    char op[9], nm[9]; trim(opf, 8, op); trim(namef, 8, nm);
    int kl = num(keylen), dl = num(datalen);
    resp(eib, 0);
    sqlite3_stmt *st;
    if (!strcmp(op, "ENTRY")) {
        static unsigned char area[32768];
        int n = get_ctl("commarea_in", area, sizeof area); if (n < 0) n = 0;
        memcpy(eib, "\x02\x35\x95\x8f", 4); memcpy(eib + 4, "\x01\x26\x30\x4f", 4);
        unsigned char tr[4] = {'T', 'R', 'N', '1'}; unsigned char tmp[8]; int t = get_ctl("transid", tmp, 8);
        if (t >= 0) { memset(tr, ' ', 4); memcpy(tr, tmp, t < 4 ? t : 4); }
        memcpy(eib + 8, tr, 4); memcpy(eib + 12, "\x00\x00\x00\x1c", 4); memcpy(eib + 16, "T001", 4);
        eib[24] = (n >> 8) & 255; eib[25] = n & 255;
        unsigned char aid[1]; eib[26] = get_ctl("aid", aid, 1) > 0 ? aid[0] : '\'';
        unsigned char bind[8];
        if (get_ctl("bind", bind, 8) >= 0) {  /* a later turn of a conversation: started by the key on the next screen */
            st = q("SELECT seq, aid FROM term_in WHERE used = 0 ORDER BY seq LIMIT 1");
            int seq = -1;
            if (sqlite3_step(st) == SQLITE_ROW) {
                seq = sqlite3_column_int(st, 0);
                const unsigned char *a = sqlite3_column_blob(st, 1);
                if (a && sqlite3_column_bytes(st, 1) > 0) eib[26] = a[0];
            }
            sqlite3_finalize(st);
            if (seq >= 0) { char sq[16]; int len = snprintf(sq, 16, "%d", seq); set_ctl("current_seq", sq, len); }
        }
        copy_out(data, dl, area, n);
        return 0;
    }
    if (!strcmp(op, "READ") || !strcmp(op, "READGE") || !strcmp(op, "READGEN")) {
        if (!strcmp(op, "READ")) st = q("SELECT key, rec FROM files WHERE file = ? AND key = ?");
        else if (!strcmp(op, "READGE")) st = q("SELECT key, rec FROM files WHERE file = ? AND key >= ? ORDER BY key LIMIT 1");
        else st = q("SELECT key, rec FROM files WHERE file = ? AND substr(key, 1, ?3) = ?2 ORDER BY key LIMIT 1");
        sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_bind_blob(st, 2, key, kl, T);
        if (!strcmp(op, "READGEN")) sqlite3_bind_int(st, 3, kl);
        if (sqlite3_step(st) != SQLITE_ROW) { sqlite3_finalize(st); resp(eib, 13); return 0; }
        int rn = sqlite3_column_bytes(st, 1);
        copy_out(data, dl, sqlite3_column_blob(st, 1), rn);
        put_num(datalen, rn);
        int s = slot(last, sizeof last[0], 16, nm);
        last[s].len = sqlite3_column_bytes(st, 0); if (last[s].len > 256) last[s].len = 256;
        memcpy(last[s].key, sqlite3_column_blob(st, 0), last[s].len); last[s].has = 1;
        sqlite3_finalize(st);
        if (rn > dl) resp(eib, 22);
        return 0;
    }
    if (!strcmp(op, "WRITE")) {
        st = q("INSERT INTO files VALUES (?, ?, ?)");
        sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_bind_blob(st, 2, key, kl, T); sqlite3_bind_blob(st, 3, data, dl, T);
        if (sqlite3_step(st) != SQLITE_DONE) resp(eib, 14);
        sqlite3_finalize(st); return 0;
    }
    if (!strcmp(op, "REWRITE")) {
        int s = slot(last, sizeof last[0], 16, nm);
        if (!last[s].has) { resp(eib, 16); return 0; }
        st = q("UPDATE files SET rec = ? WHERE file = ? AND key = ?");
        sqlite3_bind_blob(st, 1, data, dl, T); sqlite3_bind_text(st, 2, nm, -1, T); sqlite3_bind_blob(st, 3, last[s].key, last[s].len, T);
        sqlite3_step(st); sqlite3_finalize(st); last[s].has = 0; return 0;
    }
    if (!strcmp(op, "DELETE")) {
        int s = slot(last, sizeof last[0], 16, nm);
        const unsigned char *k = key; int n = kl;
        if (!kl) { if (!last[s].has) { resp(eib, 16); return 0; } k = last[s].key; n = last[s].len; }
        st = q("DELETE FROM files WHERE file = ? AND key = ?");
        sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_bind_blob(st, 2, k, n, T);
        sqlite3_step(st); sqlite3_finalize(st);
        if (!kl) last[s].has = 0;
        if (sqlite3_changes(db) == 0) resp(eib, 13);
        return 0;
    }
    if (!strcmp(op, "STARTBR")) {
        st = q("SELECT 1 FROM files WHERE file = ? AND key >= ? LIMIT 1");
        sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_bind_blob(st, 2, key, kl, T);
        int found = sqlite3_step(st) == SQLITE_ROW; sqlite3_finalize(st);
        if (!found) { resp(eib, 13); return 0; }
        int s = slot(brw, sizeof brw[0], 16, nm);
        memcpy(brw[s].pos, key, kl); brw[s].len = kl; brw[s].incl = 1; brw[s].has = 1;
        return 0;
    }
    if (!strcmp(op, "READNEXT") || !strcmp(op, "READPREV")) {
        int s = slot(brw, sizeof brw[0], 16, nm);
        if (!brw[s].has) { resp(eib, 16); return 0; }
        int next = !strcmp(op, "READNEXT");
        const char *sql = next ? (brw[s].incl ? "SELECT key, rec FROM files WHERE file = ? AND key >= ? ORDER BY key LIMIT 1"
                                              : "SELECT key, rec FROM files WHERE file = ? AND key > ? ORDER BY key LIMIT 1")
                               : (brw[s].incl ? "SELECT key, rec FROM files WHERE file = ? AND key <= ? ORDER BY key DESC LIMIT 1"
                                              : "SELECT key, rec FROM files WHERE file = ? AND key < ? ORDER BY key DESC LIMIT 1");
        st = q(sql);
        sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_bind_blob(st, 2, brw[s].pos, brw[s].len, T);
        if (sqlite3_step(st) != SQLITE_ROW) { sqlite3_finalize(st); resp(eib, 20); return 0; }
        int rn = sqlite3_column_bytes(st, 1), kn = sqlite3_column_bytes(st, 0);
        copy_out(data, dl, sqlite3_column_blob(st, 1), rn);
        put_num(datalen, rn);
        if (kn > 256) kn = 256;
        memcpy(brw[s].pos, sqlite3_column_blob(st, 0), kn); brw[s].len = kn; brw[s].incl = 0;
        memcpy(key, brw[s].pos, kn < kl ? kn : kl);
        int l = slot(last, sizeof last[0], 16, nm); memcpy(last[l].key, brw[s].pos, kn); last[l].len = kn; last[l].has = 1;
        sqlite3_finalize(st);
        return 0;
    }
    if (!strcmp(op, "ENDBR")) { int s = slot(brw, sizeof brw[0], 16, nm); if (!brw[s].has) resp(eib, 16); brw[s].has = 0; return 0; }
    if (!strcmp(op, "SEND") || !strcmp(op, "SENDMAP")) {
        char kind[16]; if (!strcmp(op, "SEND")) strcpy(kind, "TEXT"); else snprintf(kind, 16, "MAP %s", nm);
        st = q("INSERT INTO term_out (kind, data) VALUES (?, ?)");
        sqlite3_bind_text(st, 1, kind, -1, T); sqlite3_bind_blob(st, 2, data, dl, T);
        sqlite3_step(st); sqlite3_finalize(st); return 0;
    }
    if (!strcmp(op, "RECEIVE")) {
        st = q("SELECT seq, aid, data FROM term_in WHERE used = 0 ORDER BY seq LIMIT 1");
        if (sqlite3_step(st) != SQLITE_ROW) { sqlite3_finalize(st); resp(eib, 36); return 0; }
        int seq = sqlite3_column_int(st, 0);
        const unsigned char *a = sqlite3_column_blob(st, 1);
        eib[26] = (a && sqlite3_column_bytes(st, 1) > 0) ? a[0] : '\'';
        int n = sqlite3_column_bytes(st, 2);
        /* CLEAR and the PA keys send no data, and neither does an empty screen: MAPFAIL, nothing moved */
        int nodata = n == 0 || eib[26] == '_' || eib[26] == '%' || eib[26] == '>' || eib[26] == ',';
        if (!nodata) {
            copy_out(data, dl, sqlite3_column_blob(st, 2), n);
            if (n < dl) memset(data + n, ' ', dl - n);
            put_num(datalen, n);
        }
        sqlite3_finalize(st);
        st = q("UPDATE term_in SET used = 1 WHERE seq = ?"); sqlite3_bind_int(st, 1, seq); sqlite3_step(st); sqlite3_finalize(st);
        if (nodata) resp(eib, 36);
        return 0;
    }
    if (!strcmp(op, "WRITEQTS")) {
        st = q("SELECT COALESCE(MAX(item), 0) FROM tsq WHERE queue = ?"); sqlite3_bind_text(st, 1, nm, -1, T);
        sqlite3_step(st); int top = sqlite3_column_int(st, 0); sqlite3_finalize(st);
        st = q("INSERT INTO tsq VALUES (?, ?, ?)");
        sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_bind_int(st, 2, top + 1); sqlite3_bind_blob(st, 3, data, dl, T);
        sqlite3_step(st); sqlite3_finalize(st); put_num(item, top + 1); return 0;
    }
    if (!strcmp(op, "READQTS")) {
        st = q("SELECT 1 FROM tsq WHERE queue = ? LIMIT 1"); sqlite3_bind_text(st, 1, nm, -1, T);
        int any = sqlite3_step(st) == SQLITE_ROW; sqlite3_finalize(st);
        if (!any) { resp(eib, 44); return 0; }
        int p = slot(qpos, sizeof qpos[0], 16, nm);
        int want = num(item); if (!want) want = qpos[p].pos + 1;
        st = q("SELECT data FROM tsq WHERE queue = ? AND item = ?"); sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_bind_int(st, 2, want);
        if (sqlite3_step(st) != SQLITE_ROW) { sqlite3_finalize(st); resp(eib, 26); return 0; }
        copy_out(data, dl, sqlite3_column_blob(st, 0), sqlite3_column_bytes(st, 0));
        sqlite3_finalize(st); qpos[p].pos = want; put_num(item, want); return 0;
    }
    if (!strcmp(op, "WRITEQTD") || !strcmp(op, "READQTD") || !strcmp(op, "DELQTD")) {  /* kept in tsq as 'TD:' + name */
        char tq[16]; snprintf(tq, 16, "TD:%s", nm);
        if (!strcmp(op, "WRITEQTD")) {
            st = q("SELECT COALESCE(MAX(item), 0) FROM tsq WHERE queue = ?"); sqlite3_bind_text(st, 1, tq, -1, T);
            sqlite3_step(st); int top = sqlite3_column_int(st, 0); sqlite3_finalize(st);
            st = q("INSERT INTO tsq VALUES (?, ?, ?)");
            sqlite3_bind_text(st, 1, tq, -1, T); sqlite3_bind_int(st, 2, top + 1); sqlite3_bind_blob(st, 3, data, dl, T);
            sqlite3_step(st); sqlite3_finalize(st);
        } else if (!strcmp(op, "READQTD")) {
            st = q("SELECT item, data FROM tsq WHERE queue = ? ORDER BY item LIMIT 1"); sqlite3_bind_text(st, 1, tq, -1, T);
            if (sqlite3_step(st) != SQLITE_ROW) { sqlite3_finalize(st); resp(eib, 23); return 0; }
            int it = sqlite3_column_int(st, 0), n = sqlite3_column_bytes(st, 1);
            copy_out(data, dl, sqlite3_column_blob(st, 1), n); put_num(datalen, n);
            sqlite3_finalize(st);
            st = q("DELETE FROM tsq WHERE queue = ? AND item = ?"); sqlite3_bind_text(st, 1, tq, -1, T); sqlite3_bind_int(st, 2, it);
            sqlite3_step(st); sqlite3_finalize(st);
        } else {
            st = q("DELETE FROM tsq WHERE queue = ?"); sqlite3_bind_text(st, 1, tq, -1, T); sqlite3_step(st); sqlite3_finalize(st);
        }
        return 0;
    }
    if (!strcmp(op, "DELQTS")) {
        st = q("DELETE FROM tsq WHERE queue = ?"); sqlite3_bind_text(st, 1, nm, -1, T); sqlite3_step(st); sqlite3_finalize(st);
        if (sqlite3_changes(db) == 0) resp(eib, 44);
        int p = slot(qpos, sizeof qpos[0], 16, nm); qpos[p].pos = 0; return 0;
    }
    if (!strcmp(op, "RETURN")) { set_ctl("return_transid", nm, (int)strlen(nm)); set_ctl("return_commarea", data, dl); return 0; }
    if (!strcmp(op, "ABEND")) { set_ctl("abend", nm, (int)strlen(nm)); return 0; }
    if (!strcmp(op, "SYNCPNT")) return 0;
    resp(eib, 16);
    return 0;
}
