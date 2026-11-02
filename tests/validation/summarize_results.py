"""Aggregate immutable validation evidence; does not run CAD or fix production code."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def hashes(project):
    return {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (project / "src").rglob("*.py")}


def stl_evidence(path):
    raw = path.read_bytes()
    count = struct.unpack("<I", raw[80:84])[0] if len(raw) >= 84 else -1
    if len(raw) != 84 + 50 * count:
        return {"format": "ASCII or unrecognized binary", "bytes": len(raw)}
    vertices = []
    edges = Counter()
    signed_volume = 0.0
    for index in range(count):
        values = struct.unpack_from("<12fH", raw, 84 + 50 * index)
        triangle = [tuple(round(v, 9) for v in values[start:start + 3]) for start in [3, 6, 9]]
        assert all(math.isfinite(v) for vertex in triangle for v in vertex)
        a, b, c = triangle
        signed_volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
                          - a[1] * (b[0] * c[2] - b[2] * c[0])
                          + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
        vertices.extend(triangle)
        for start, end in [(a, b), (b, c), (c, a)]:
            edges[tuple(sorted((start, end)))] += 1
    assert all(incidence == 2 for incidence in edges.values()), "STL is not a closed two-manifold mesh"
    return {"format": "binary", "triangles": count, "unique_vertices": len(set(vertices)),
            "watertight_edge_incidence": True, "absolute_volume_in_file_units_cubed": abs(signed_volume),
            "bounds_in_unitless_file_coordinates": [[min(v[i] for v in vertices), max(v[i] for v in vertices)]
                                                    for i in range(3)],
            "unit_caution": "STL has no standardized embedded physical length unit"}


def pids(tasklist_csv):
    return {int(row[1]) for row in csv.reader(io.StringIO(tasklist_csv))
            if len(row) >= 2 and row[0].lower() == "sldworks.exe" and row[1].isdigit()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    root, project = args.output_root.resolve(), args.project_root.resolve()
    assert root.parent == Path("D:/New folder (2)").resolve() and root.is_dir()
    manifest = load(root / "run_manifest.json")
    reports = {"Core offline": load(root / "core_report.json"),
               "Domain CAD offline": load(root / "domains_report.json"),
               "Protocol + contract/documentation": load(root / "protocol_report.json")}
    runs = [root, root / "live_isolated_r2", root / "live_followup_r3", root / "live_final_r4"]
    latest = {}
    run_summaries = []
    successful_tools, attempted_tools = set(), set()
    request_count = 0
    for folder in runs:
        report = load(folder / "live_report.json")
        run_summaries.append({"directory": str(folder), "counts": report["counts"], "cases": report["case_count"]})
        for case in report["records"]:
            latest[case["name"]] = {**case, "evidence_directory": str(folder)}
        requests = load(folder / "live_wire_requests.json")
        request_count += len(requests)
        for exchange in requests:
            request = exchange["request"]
            if request["method"] != "tools/call":
                continue
            name = request["params"]["name"]
            attempted_tools.add(name)
            result = exchange.get("response", {}).get("result")
            if result and not result.get("isError"):
                successful_tools.add(name)
    effective_counts = dict(Counter(case["status"] for case in latest.values()))
    assert len(latest) == 72 and effective_counts == {"pass": 65, "fail": 7}
    assert len(attempted_tools) == 48 and len(successful_tools) == 48
    source_after = hashes(project)
    source_before = load(root / "production_hashes_initial.json")
    assert source_before == source_after, "Production code changed during the audit"
    (root / "production_hashes_final.json").write_text(json.dumps(source_after, indent=2), encoding="utf-8")
    compiled = []
    for base in [project / "src", project / "tests" / "validation"]:
        for path in sorted(base.rglob("*.py")):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            compiled.append(str(path.relative_to(project)))
    final_processes = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV"],
                                     capture_output=True, text=True, timeout=10)
    final_processes.check_returncode()
    initial_pids, final_pids = pids(manifest["solidworks_processes"]), pids(final_processes.stdout)
    cleanup = load(root / "live_cleanup_final.json")
    assert cleanup["remaining_documents"] == []
    artifacts = []
    ole_header = bytes.fromhex("D0CF11E0A1B11AE1")
    for folder in runs:
        for path in sorted((folder / "models").glob("*")):
            if path.suffix.lower() not in {".sldprt", ".sldasm", ".slddrw"} or path.name.startswith("~$"):
                continue
            data = path.read_bytes()
            assert len(data) > 100, f"Native CAD artifact is missing/empty: {path}"
            artifacts.append({"path": str(path), "bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest(), "header_hex": data[:32].hex(),
                              "container": "legacy OLE" if data.startswith(ole_header)
                              else "SolidWorks version-specific native format; not independently parsed"})
    stl = root / "live_isolated_r2" / "exports" / "validation_block.stl"
    stl_check = stl_evidence(stl)
    igs = root / "live_followup_r3" / "exports" / "validation_block.igs"
    igs_lines = igs.read_text(encoding="ascii", errors="replace").splitlines()
    igs_sections = Counter(line[72:73] for line in igs_lines if line)
    assert all(len(line) == 80 for line in igs_lines if line), "IGES record length is not 80 columns"
    assert {"S", "G", "D", "P", "T"}.issubset(igs_sections)
    assert igs_lines[-1][72:73] == "T"
    step = root / "live_isolated_r2" / "exports" / "validation_block.step"
    step_schema = re.search(r"FILE_SCHEMA\s*\(([^;]+)\);", step.read_text(encoding="ascii", errors="replace"))
    syntax_and_integrity = {
        "syntax_compiled_files": compiled, "production_source_unchanged": True,
        "production_python_files": len(source_after), "native_artifacts_catalogued": len(artifacts),
        "native_artifacts": artifacts, "stl": stl_check,
        "iges": {"path": str(igs), "record_count": len(igs_lines), "sections": dict(igs_sections), "records_80_columns": True},
        "step_schema": step_schema.group(1) if step_schema else None,
        "solidworks_pids_before": sorted(initial_pids), "solidworks_pids_after": sorted(final_pids),
        "all_initial_solidworks_pids_still_running": initial_pids.issubset(final_pids),
        "audit_document_cleanup": cleanup,
        "editor_diagnostics": "Not clean: editor reported diagnostics in production and dynamic test harnesses. Syntax compilation passed separately; no claim that static typing/lint passed.",
    }
    (root / "integrity_verification.json").write_text(json.dumps(syntax_and_integrity, indent=2), encoding="utf-8")
    summary = {
        "created_at": datetime.now().astimezone().isoformat(),
        "verdict": "Primary CAD workflows function, but confirmed safety/design defects remain; not approved for unattended production",
        "environment": manifest,
        "suites": {name: report["counts"] for name, report in reports.items()},
        "live_unique_case_counts": {"total": len(latest), **effective_counts},
        "live_raw_runs": run_summaries, "live_latest_cases": list(latest.values()),
        "real_live_mcp_requests": request_count, "distinct_tools_attempted": sorted(attempted_tools),
        "distinct_tools_with_successful_response": sorted(successful_tools),
        "counting_notes": [
            "Parameterized robustness cases are not distinct production bugs; no branch-coverage percentage is claimed.",
            "Live cases are deduplicated by scenario name, using the latest valid run; raw evidence is retained.",
            "R1 shared-fixture cascade and R2/R3 harness name/type/accessor issues were isolated/corrected without changing production code.",
            "Seven live failures include edge visibility sensitivity and unsupported .iges spelling; .igs and visible/preselected edge controls passed.",
            "All 48 tools returning success at least once does not prove all argument variants or CAD semantics correct.",
        ],
        "integrity": syntax_and_integrity,
        "limitations": ["Only installed SolidWorks revision 34.4.1 and current Python/MCP environment tested",
                        "Only selected materials/configurations and coincident/parallel/distance mates exercised live",
                        "Dangerous fault injection (cancelled mutation/rollback selection failure) used mocks, not user documents",
                        "Five-cycle bounded repetition per main run, not an hours-long soak or crash/power-loss certification",
                        "Drawing creation/export and two actual dimensions are not full GD&T/manufacturability certification",
                        "Initial ROT lookup failed; normal production Dispatch fallback was exercised successfully",
                        "No destructive testing of existing documents, process kill, dependency installation, or network services"],
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    rows = ["| Suite | Cases | Pass | Fail | Skip |", "|---|---:|---:|---:|---:|"]
    for name, report in reports.items():
        count = report["counts"]
        rows.append(f"| {name} | {count['total']} | {count['pass']} | {count['fail']} | {count['skip']} |")
    rows.append(f"| Live, latest result per scenario | {len(latest)} | {effective_counts['pass']} | {effective_counts['fail']} | 0 |")
    text = """# SolidWorks MCP — laporan pengujian nyata

## Kesimpulan

Alur CAD utama berfungsi pada SolidWorks **34.4.1 / 2026 SP4.1**, tetapi masih ada defect keselamatan dan ketepatan desain. **Belum disetujui untuk produksi tanpa pengawasan.** Source produksi tidak diubah; yang ditambahkan hanya harness pengujian dan laporan.

Lokasi artefak: `OUTPUT_ROOT`.

## Hasil terukur

TABLE

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
""".replace("OUTPUT_ROOT", str(root)).replace("TABLE", "\n".join(rows))
    (root / "REPORT.md").write_text(text, encoding="utf-8")
    (project / "tests" / "validation" / "REPORT.md").write_text(text, encoding="utf-8")
    shutil.copyfile(__file__, root / "summarize_results.py")
    print(json.dumps({"report": str(root / "REPORT.md"), "suite_counts": summary["suites"],
                      "live_unique": summary["live_unique_case_counts"],
                      "real_live_requests": request_count, "tools_with_success": len(successful_tools),
                      "production_files_unchanged": len(source_after), "syntax_files": len(compiled),
                      "native_cad_artifacts": len(artifacts), "stl": stl_check,
                      "initial_pids_preserved": initial_pids.issubset(final_pids),
                      "final_session_documents": cleanup["remaining_documents"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
