/*
 * First-boot fixer for the A40 iOS 16 root (built on macOS without root:
 * every copied file belongs to the build user). Runs as pid 1 instead of
 * launchd (boot-arg launchdsuffix=a40fix -> /usr/appleinternal/sbin/launchd.a40fix),
 * applies /a40fix.manifest ("uid gid mode path" per line, octal mode,
 * mode 0 = keep), syncs and halts. Static, no libSystem: raw syscalls.
 */
typedef unsigned long u64;
typedef long s64;

static s64 sys(u64 n, u64 a, u64 b, u64 c)
{
	register u64 x0 __asm__("x0") = a, x1 __asm__("x1") = b, x2 __asm__("x2") = c, x16 __asm__("x16") = n;
	__asm__ volatile("svc #0x80\n b.cc 1f\n neg x0, x0\n1:" : "+r"(x0), "+r"(x1), "+r"(x2) : "r"(x16) : "memory", "cc");
	return (s64)x0;
}
#define SYS_exit 1
#define SYS_read 3
#define SYS_write 4
#define SYS_open 5
#define SYS_close 6
#define SYS_chmod 15
#define SYS_sync 36
#define SYS_reboot 55
#define SYS_lchown 364
#define SYS_unlink 10

static int con = 1;
static u64 slen(const char *s) { u64 n = 0; while (s[n]) n++; return n; }
static void out(const char *s) { sys(SYS_write, con, (u64)s, slen(s)); }
static void outn(s64 v)
{
	char b[24]; int i = 23; b[i] = 0; int neg = v < 0; u64 u = neg ? -v : v;
	do { b[--i] = '0' + u % 10; u /= 10; } while (u);
	if (neg) b[--i] = '-';
	out(b + i);
}

static char buf[1 << 20];

void start(void) __asm__("start");
void start(void)
{
	s64 c = sys(SYS_open, (u64)"/dev/console", 2, 0);
	if (c >= 0) con = (int)c;
	out("\n=== A40 FIX: applying /a40fix.manifest ===\n");
	s64 fd = sys(SYS_open, (u64)"/a40fix.manifest", 0, 0);
	if (fd < 0) { out("A40 FIX: no manifest, errno "); outn(-fd); out("\n"); goto end; }
	u64 have = 0, lines = 0, errs = 0;
	for (;;) {
		s64 n = sys(SYS_read, fd, (u64)(buf + have), sizeof(buf) - 1 - have);
		if (n < 0) { out("read error\n"); break; }
		have += n;
		if (have == 0) break;
		u64 start = 0;
		for (u64 i = 0; i < have; i++) {
			if (buf[i] != '\n') continue;
			buf[i] = 0;
			char *l = buf + start;
			start = i + 1;
			u64 v[3] = {0, 0, 0};
			int k = 0;
			while (k < 3) {
				u64 x = 0;
				int base = k == 2 ? 8 : 10;
				while (*l >= '0' && *l <= '9') x = x * base + (*l++ - '0');
				v[k++] = x;
				if (*l == ' ') l++;
			}
			s64 r = sys(SYS_lchown, (u64)l, v[0], v[1]);
			if (r < 0 && errs < 20) { out("lchown "); outn(-r); out(" "); out(l); out("\n"); }
			if (r < 0) errs++;
			if (v[2]) {
				r = sys(SYS_chmod, (u64)l, v[2], 0);
				if (r < 0 && errs < 20) { out("chmod "); outn(-r); out(" "); out(l); out("\n"); }
				if (r < 0) errs++;
			}
			if ((++lines % 20000) == 0) { out("A40 FIX: "); outn(lines); out(" entries\n"); }
		}
		for (u64 i = start; i < have; i++) buf[i - start] = buf[i];
		have -= start;
		if (n == 0) break;
	}
	sys(SYS_close, fd, 0, 0);
	out("A40 FIX: done, "); outn(lines); out(" entries, "); outn(errs); out(" errors\n");
	sys(SYS_unlink, (u64)"/a40fix.manifest", 0, 0);
end:
	sys(SYS_sync, 0, 0, 0);
	sys(SYS_sync, 0, 0, 0);
	out("=== A40 FIX: halting (RB_HALT) ===\n");
	sys(SYS_reboot, 8, 0, 0);
	for (;;) ;
}
