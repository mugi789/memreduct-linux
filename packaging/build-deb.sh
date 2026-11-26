#!/usr/bin/env bash
# Membangun paket .deb MemReduct. Hasil: dist/memreduct_<versi>_all.deb
# Pemakaian: bash packaging/build-deb.sh   (atau: make deb)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
PKG="memreduct_${VERSION}_all"
STAGE="$ROOT/build/$PKG"
OUT="$ROOT/dist"

command -v dpkg-deb >/dev/null || { echo "dpkg-deb tidak ditemukan (jalankan di Debian/Ubuntu)" >&2; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/lib/memreduct" "$OUT"

# berkas statis (ikon, desktop entry, launcher, sudoers)
cp -a "$ROOT/packaging/files/." "$STAGE/"

# aplikasi
install -m 0644 "$ROOT/src/memreduct.py" "$STAGE/usr/lib/memreduct/memreduct.py"

# helper root diambil dari HELPER_SCRIPT di memreduct.py (satu sumber kebenaran)
python3 - "$ROOT/src/memreduct.py" "$STAGE/usr/lib/memreduct/memreduct-clean" <<'PY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'HELPER_SCRIPT = """(.*?)"""', src, re.S)
if not m:
    sys.exit("HELPER_SCRIPT tidak ditemukan di memreduct.py")
open(sys.argv[2], "w", encoding="utf-8").write(m.group(1))
PY
bash -n "$STAGE/usr/lib/memreduct/memreduct-clean"

# metadata paket
sed "s/@VERSION@/$VERSION/" "$ROOT/packaging/debian/control.in" > "$STAGE/DEBIAN/control"
cp "$ROOT/packaging/debian/postinst" "$ROOT/packaging/debian/postrm" "$ROOT/packaging/debian/conffiles" "$STAGE/DEBIAN/"

# izin file (git/zip tidak menjaga semuanya, jadi ditetapkan eksplisit)
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm" \
           "$STAGE/usr/bin/memreduct" "$STAGE/usr/lib/memreduct/memreduct-clean"
chmod 0440 "$STAGE/etc/sudoers.d/memreduct"

dpkg-deb --root-owner-group --build "$STAGE" "$OUT/$PKG.deb"
echo "Selesai: $OUT/$PKG.deb"
