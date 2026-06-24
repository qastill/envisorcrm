# Envisor CRM — Pipeline kVArh (UID Jabar)

Dashboard CRM untuk prospek pemasangan kapasitor bank, berbasis analisa denda
kVArh dari data OLAP JABAR. Dashboard selalu menampilkan **3 bulan terbaru**
secara otomatis (rolling) dan ikut terupdate setiap ada data bulan baru.

## Struktur

| File | Fungsi |
|------|--------|
| `index.html` | Aplikasi dashboard (kartu, tabel, analisa, treemap, pipeline CRM). Data-driven & month-agnostic. |
| `data.json` | Sumber data yang ditampilkan (`{meta, leads, hierarchy}`). **Inilah file yang diganti tiap bulan.** |
| `colab/ENVISOR_Web_Export.ipynb` | Notebook Colab — baca folder Drive `OLAP JABAR 2025`, hitung analisa, hasilkan `envisor_web_data.json`. |
| `colab/envisor_web_export.py` | Versi script dari notebook (boleh di-paste ke notebook lama). |

## Cara melihat

Harus disajikan lewat web server (karena `index.html` me-`fetch('data.json')`):

```bash
python3 -m http.server   # lalu buka http://localhost:8000
```

atau aktifkan **GitHub Pages** pada repo ini (Settings → Pages → branch).

## Alur update tiap bulan

```
Upload OLAP bulan baru ke Drive  →  Run-all notebook Colab  →  minta Claude "publish dashboard"
```

1. **Upload** file OLAP bulan baru ke folder Google Drive `OLAP JABAR 2025`
   (format nama bebas asal memuat nama bulan + tahun, mis. `17. Mei 2026.csv`).
2. **Buka** `colab/ENVISOR_Web_Export.ipynb` di Google Colab
   (Colab → File → Open notebook → GitHub → repo ini), lalu **Runtime → Run all**.
   Notebook menulis `envisor_web_data.json` (±1–2 MB) ke folder Drive yang sama.
3. **Minta Claude** *"publish dashboard"*. Claude akan menarik
   `envisor_web_data.json` dari Drive (≤10 MB, lewat channel resmi), menaruhnya
   sebagai `data.json` di repo, lalu push. Dashboard langsung menampilkan
   3 bulan terbaru.

> Catatan teknis: file OLAP mentah berukuran 50–68 MB sehingga **tidak** bisa
> ditarik langsung di lingkungan Claude (cap 10 MB + kebijakan egress). Karena
> itu Colab yang melakukan pemrosesan berat, dan Claude cukup mem-publish hasil
> ringkasnya. Edit CRM (stage, kontak, catatan) tersimpan di browser
> (localStorage) per `id` pelanggan, jadi **tidak hilang** saat data di-refresh.

## Tab 💡 Insight Jual

Tab khusus untuk men-_drive_ penjualan, dihitung otomatis dari data yang sedang
tampil (ikut filter aktif & bulan terbaru):

- **KPI peluang**: potensi pasar/tahun, uang hangus 3 bulan, nilai proyek
  (pipeline), total kVAR, potensi fee ENVISOR 10%/tahun, jumlah _chronic_ 3 bulan.
- **Tren denda** 3 bulan + indikator naik/turun (argumen urgensi).
- **Payback band** (ROI ≤6 / 7–12 / 13–24 / >24 bln) — fokus closing cepat.
- **Segmen tarif** & **Top UP3** (klik untuk langsung memfilter dashboard).
- **Mix produk** (ukuran kapasitor) & **komposisi prioritas**.
- **Daftar tembak**: 12 paling mudah closing (chronic + ROI tercepat) dan 12
  tiket terbesar, lengkap tombol **📋 Pitch** (menyalin narasi penawaran siap kirim).

## Rumus analisa (terverifikasi 1:1 dengan build awal)

```
denda            = RPKVARH per bulan
denda_avg        = rata-rata RPKVARH atas bulan yang kena denda
jam_nyala        = kolom JAMNYALA (rata-rata)             # bukan kWh/daya
tarif_kvarh      = {I3/I3P:1114, B3:1050, S2/I2:900, P2/S2K:950, lainnya:1000}
kvar_min         = round((denda_avg / tarif_kvarh) / jam_nyala)
kvar_rec         = round(1.2 × kvar_min)
harga_kvar       = 550.000 (daya > 1 MVA) | 300.000 (≤ 1 MVA)
invest_est       = kvar_rec × harga_kvar + 10.000.000     # +biaya pasang
roi_bulan        = min(99, invest_est / denda_avg)
rasio            = denda_avg / tagihan × 100
prioritas        = 3 bln: ≥30jt URGENT, lainnya HIGH
                   2 bln: ≥50jt HIGH,  lainnya MEDIUM
                   1 bln: ≥10jt MEDIUM, lainnya LOW
```
