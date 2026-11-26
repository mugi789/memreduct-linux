# MemReduct untuk Linux

Pembersih memori ringan untuk Ubuntu/Debian dengan ikon di system tray, terinspirasi
[Mem Reduct](https://github.com/henrypp/memreduct) di Windows. Memantau RAM, swap, dan cache, lalu
membersihkan cache secara otomatis saat pemakaian melewati ambang batas (default 80%).

> Tambahkan tangkapan layar di folder `docs/` lalu tampilkan di sini:
> `![MemReduct](docs/screenshot.png)`

## Fitur

- Ikon tray berisi angka persen RAM, warna hijau / kuning / merah sesuai batas.
- Jendela modern (GTK 3, tema gelap): gauge animasi, grafik riwayat 2 menit, tile RAM tersedia / cache / swap.
- Pembersihan otomatis: saat RAM mencapai ambang, berkala setiap N menit, atau saat aplikasi dimulai.
- Area pembersihan bisa dipilih: page cache, dentries & inodes, kompaksi memori, swap (hanya jika RAM cukup).
- Notifikasi desktop berisi hasil pembersihan.
- Opsi jalan otomatis saat login dan mulai tersembunyi di tray.
- Hemat sumber daya: gambar hanya digambar ulang saat jendela terlihat.

## Instalasi

### Dari paket .deb (disarankan)

Unduh `.deb` terbaru dari halaman **Releases**, lalu:

```bash
sudo apt install ./memreduct_1.1.0_all.deb
```

Cari **MemReduct** di menu aplikasi, atau jalankan `memreduct` (`memreduct --hidden` untuk langsung ke tray).

Hapus:

```bash
sudo apt remove memreduct
```

### Dari sumber (tanpa memasang paket)

```bash
sudo apt install python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 \
                 gir1.2-ayatanaappindicator3-0.1 libnotify-bin
python3 src/memreduct.py
```

Saat pertama kali membersihkan, aplikasi menawarkan **Siapkan izin** (meminta password admin sekali).

### Membangun .deb sendiri

```bash
make deb          # hasil: dist/memreduct_<versi>_all.deb
```

## Cara kerja dan keamanan

Membersihkan cache memerlukan hak root (`/proc/sys/vm/drop_caches`). Paket `.deb` memasang:

- `/usr/lib/memreduct/memreduct-clean`: skrip root kecil yang **hanya menerima empat kata kunci tetap**
  (`pagecache`, `slab`, `compact`, `swap`); argumen lain ditolak.
- `/etc/sudoers.d/memreduct`: mengizinkan anggota grup `sudo` menjalankan *hanya skrip itu* tanpa password.

Jika akunmu bukan anggota grup `sudo`, aplikasi meminta password admin lewat dialog polkit setiap kali
membersihkan. Aturan sudoers diperiksa dengan `visudo` saat pemasangan dan dihapus jika tidak valid.
Baca [`packaging/files/etc/sudoers.d/memreduct`](packaging/files/etc/sudoers.d/memreduct) dan
`HELPER_SCRIPT` di [`src/memreduct.py`](src/memreduct.py) bila ingin memeriksanya sendiri.

## Catatan penting

- Yang dibersihkan hanya **cache**. Memori yang dipakai aplikasi aktif tidak akan turun.
- Linux sengaja memakai RAM kosong untuk cache supaya sistem cepat. Setelah cache dibuang, akses file
  pertama bisa terasa lebih lambat, jadi pembersihan otomatis tidak wajib untuk performa harian.
- Opsi **Hitung cache sebagai terpakai** (default aktif, seperti perintah `free`) bisa dimatikan agar
  persen hanya menghitung RAM yang benar-benar dipakai aplikasi.
- Di GNOME, ikon tray memerlukan ekstensi AppIndicator (bawaan Ubuntu). Klik ikon membuka menu;
  pakai **Tampilkan jendela** untuk membuka jendela utama.

## Konfigurasi

Tersimpan di `~/.config/memreduct/config.json` (diubah lewat jendela Pengaturan). Ikon tray yang dibuat
disimpan di `~/.cache/memreduct/icons/` dan aman dihapus.

## Struktur repositori

```
src/memreduct.py              aplikasi (GTK 3 + AppIndicator)
packaging/build-deb.sh        pembangun paket .deb
packaging/debian/             metadata paket (control.in, postinst, postrm)
packaging/files/              launcher, desktop entry, ikon, aturan sudoers
.github/workflows/            CI: build .deb, rilis otomatis saat tag vX.Y.Z
VERSION                       nomor versi (sumber untuk paket dan rilis)
```

## Merilis versi baru

1. Ubah `VERSION` dan `CHANGELOG.md`.
2. `git tag v1.2.0 && git push --tags`. GitHub Actions membangun `.deb` dan melampirkannya ke Release.

## Lisensi

[MIT](LICENSE)
