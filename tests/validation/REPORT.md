# SolidWorks MCP — laporan pengujian nyata

## Kesimpulan

Alur CAD utama berfungsi pada SolidWorks **34.4.1 / 2026 SP4.1**, tetapi masih ada defect keselamatan dan ketepatan desain. **Belum disetujui untuk produksi tanpa pengawasan.** Source produksi tidak diubah; yang ditambahkan hanya harness pengujian dan laporan.

Lokasi artefak: `D:\New folder (2)\solidworks_mcp_validation_20261101_204158_cc3d1b`.

## Hasil terukur

| Suite | Cases | Pass | Fail | Skip |
|---|---:|---:|---:|---:|
| Core offline | 817 | 632 | 185 | 0 |
| Domain CAD offline | 106 | 95 | 8 | 3 |
| Protocol + contract/documentation | 912 | 904 | 7 | 1 |
| Live, latest result per scenario | 72 | 65 | 7 | 0 |

**48/48 tool** dipanggil melalui server MCP nyata, dan masing-masing setidaknya pernah mengembalikan respons sukses. Empat tahap live menghasilkan **1507 request JSON-RPC**. Ini bukan bukti semua kombinasi parameter benar. Banyak kegagalan offline adalah variasi batas input/robustness, bukan jumlah bug yang berbeda.

Tujuh kegagalan suite protokol adalah metadata/dokumentasi (alias yang tidak tercantum pada katalog “exact”, jumlah tool pada heading, nama server, dan required/default); handshake, discovery, framing stdio, error validation, serta forwarding 48 wrapper lulus. Lihat `protocol_report.json`.

## Temuan prioritas

### P1 — Queue dan rollback (terbukti pada mock offline, sengaja tidak diuji destruktif pada CAD live)

- Mutasi antrean yang future-nya dibatalkan tetap dieksekusi. Stop timeout dapat melupakan thread yang masih hidup dan restart membuka worker pengganti sebelum yang lama selesai. Drain antrean juga meninggalkan unfinished-task accounting. Sumber: `src/sw_mcp/core/sta_worker.py`. Bukti: kasus `cancel_pending_mutation_*`, `stop_timeout_does_not_forget_live_sta`, `restart_cannot_overlap_timed_out_sta` di `core_report.json`.
- Rollback tetap memanggil `EditDelete` ketika `feat.Select2` gagal. Pada mock dengan selection lama masih ada, objek lama dapat menjadi target. Pesan “rolled back” juga tidak memeriksa keberhasilan delete. Ini risiko, bukan klaim dokumen pengguna benar-benar terhapus. Sumber: `src/sw_mcp/cad/features.py`; bukti `rollback_selection_failure_*`, `rollback_delete_failure_*`.

### P1 — Konfigurasi komponen salah (live)

Permintaan `config_name="Default"` menghasilkan komponen yang **ReferencedConfiguration-nya `AuditAlternate`**. Native COM hanya dipakai untuk membuat fixture dua konfigurasi dan membaca hasil; insertion dilakukan oleh MCP produksi. Sumber: `src/sw_mcp/cad/assembly.py:176` (`UseConfigForPartReferences=False`). Bukti: `live_final_r4/live_native_evidence.json` dan kasus `assembly.requested_configuration_actual_reference`.

### P1 — Layout first-angle salah (live)

Setelah sheet uji benar-benar diset first-angle, standard views tetap memakai layout third-angle: Front `[140,100]`, Top `[140,150]`, Right `[190,100]` mm. Untuk first-angle, Top seharusnya di bawah dan Right di kiri. Template third-angle default lulus. Sumber: `src/sw_mcp/cad/drawing.py`, `create_standard_views`; bukti `live_final_r4/live_first_angle_evidence.json`.

### P1 — Plane yang tidak ada diterima diam-diam (live)

`sw_create_sketch_on_plane(plane_name="__AUDIT_MISSING_PLANE__")` mengembalikan sketch aktif dan nama fiktif tersebut, padahal fallback memilih Front Plane. Sumber: `src/sw_mcp/cad/sketcher.py:45–62`; bukti `sketch.unknown_plane_must_not_silently_use_front` di laporan live.

### P1/P2 — SaveAs gagal masih mengubah state (live)

SaveAs ke nama ber-colon/ADS ditolak (`status=False`, error 1), tetapi title/path in-memory berganti menjadi `invalid_r2:name.SLDPRT`. Volume fixture tetap benar, jadi ini bukan bukti kehilangan geometri; state/identity yang berubah dapat mengunci dan memblokir reopen referensi asli. R1 mendeteksi efek berantai tersebut; R2 mengulang dengan fixture sekali pakai dan baseline independen. Sumber: `src/sw_mcp/cad/document.py`, `save_doc`; bukti `live_isolated_r2/live_failed_save_side_effect.json`. Validasi nama/path sebelum COM dan pelaporan partial state diperlukan.

### P2 — Keterbatasan yang terukur

- Seleksi edge `(0,0,10)` mm gagal pada view aktif. Edge depan `(25,0,20)` dan kontrol B-rep preselected sama-sama berhasil untuk fillet/chamfer. Jadi feature creation bekerja, tetapi pemilihan koordinat bergantung visibilitas/view dan belum cukup robust.
- Ekspor `.iges` gagal; **`.igs` berhasil**, termasuk pemeriksaan record IGES 80 kolom. Ini batas kompatibilitas ekstensi, bukan kegagalan seluruh format IGES.
- Offline: screenshot lama masih dapat dilaporkan sukses saat capture baru gagal; cleanup BMP gagal pada beberapa jalur; equation rebuild false masih dilaporkan true; clear material yang ditolak bisa dilaporkan sukses. Detail di `domains_report.json`.
- `force` rebuild diterima tetapi tidak mengubah perilaku. Forwarding `reverse_direction` section pada primary path tidak memengaruhi call yang dibuat. Pembuatan kedua section view lulus, tetapi arah reverse belum dijamin.

## Yang benar-benar berhasil

- Balok **50 × 30 × 20 mm**: volume **30000 mm³**, area **6200 mm²**, pusat massa **(25,15,10) mm**.
- Dimensi extrusion 20 → 25 mm mengubah volume **30000 → 37500 mm³**, lalu kembali ke 30000.
- Triangle/arc, cut-extrude, revolve boss/cut, boss/cut sweep, circular pattern enam hole: volume diperiksa terhadap hasil analitik.
- Fillet/chamfer pada edge yang terlihat dan B-rep preselection: perubahan volume diverifikasi.
- Material 6061: assignment/readback, densitas–massa, dan clear pada keadaan normal lulus.
- Save/reopen/in-place/alias; gagal save-on-close mempertahankan dokumen terbuka.
- Assembly dengan clearance dan overlap; fixed/floating readback; coincident, parallel, distance mates.
- Drawing view dan skala, empat view default, note, section, PDF/DXF/DWG/native export. Auto-dimension diverifikasi independen menghasilkan **dua display dimensions**, bukan hanya membaca status sukses.
- STEP, STL, Parasolid, IGES `.igs`; viewport PNG non-kosong; lima siklus buat–ukur–simpan–tutup pada setiap main run.

## Integritas dan keselamatan

- SHA-256 seluruh **22 file Python produksi** sebelum/sesudah identik.
- Semua file Python sumber/harness berhasil dikompilasi secara sintaksis tanpa menulis bytecode. **Lint/type checking tidak dinyatakan lulus**: editor masih melaporkan diagnostic pada produksi dan harness dinamis.
- Dokumen audit ditutup, termasuk artefak failed-SaveAs dari run pertama; inventory sesi yang diuji pada akhir **kosong**. Tidak ada dokumen non-audit yang ditutup dan tidak ada proses SolidWorks yang dihentikan oleh harness.
- Native COM pada follow-up dibatasi path dokumen milik audit: setup selection, konfigurasi, sheet first-angle, dan pembacaan bukti. Geometri/feature/mates/view dibuat melalui MCP.
- Tidak ada paket dipasang, network/service eksternal, penghapusan file pengguna, atau pengujian crash/power-loss.

## Cara membaca angka

Live R1: 28 pass / 34 fail; efek fixture bersama menyebabkan sebagian gagal berantai. R2: 54 / 8; tiga kasus mengungkap masalah harness (`name` collision dan asumsi type feature), bukan defect produk. R3: 11 / 4; kontrol native dan selector diperbaiki berdasarkan binding/type yang benar. R4: 8 / 2; kedua kegagalan final adalah konfigurasi dan first-angle yang dibuktikan independen.

Tabel memakai **72 scenario live unik, hasil terakhir per nama**, bukan menambahkan ulang skenario yang diulang. Semua laporan mentah dan snapshot script tetap disimpan. Tujuh live fail yang tersisa terdiri dari empat isu correctness/state, dua keterbatasan seleksi edge, dan satu alias ekstensi IGES.

## Batas pengujian

Hanya versi SolidWorks/Python/MCP yang terpasang, beberapa material dan tiga tipe mate yang diuji live. Ini bukan branch coverage 100%, uji seluruh versi bahasa/template, endurance berjam-jam, ataupun sertifikasi GD&T/manufaktur. Fault injection berbahaya memakai mock. Prioritas selanjutnya: queue cancellation/shutdown, rollback aman, referensi konfigurasi, first-angle, penolakan plane tak dikenal, dan state recovery SaveAs.

## Berkas bukti

- `summary.json`, `integrity_verification.json`, `production_hashes_initial.json`, `production_hashes_final.json`
- `core_report.json`, `core_tests.log`, `core_offline.py`
- `domains_report.json`, `domains_tests.log`, `domains_offline.py`
- `protocol_report.json`, `protocol_schemas.json`, `protocol_tests.log`, `protocol_wire_*`
- `live_report.json` (R1), `live_isolated_r2/`, `live_followup_r3/`, `live_final_r4/`
- Dalam setiap run live: request/response JSON-RPC, stderr server, snapshot script, models, exports, gambar PNG.

Perintah yang benar-benar dijalankan dan exit code terdapat di laporan suite serta `live_execution.json`. Test commands keluar **1** karena assertion gagal; itu bukan laporan “semua tes lulus”. Perintah peringkasan/integritas keluar 0 hanya jika bukti, jumlah kasus, syntax, dan source hash konsisten.
