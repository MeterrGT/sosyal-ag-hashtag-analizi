# Final teslim kontrolü ve çalıştırma

Bu klasör; kaynak kodu, 48 saatlik hashtag CSV'si, düzeltilmiş analiz çıktıları ve final teslim dosyalarını içerir. Ara teslimde kullandığın `sosyal_ag_baslangic` klasöründen ayrı final kopyası olarak hazırlanmıştır.

## Şu an hazır olan teslim dosyaları

- `deliverables/2516016026_METEHAN_GEZER_Rapor.pdf` — 8 sayfa.
- `deliverables/hashtag_network_poster_A3.pdf` — tek sayfa A3 poster.
- `deliverables/2516016026_METEHAN_GEZER_Sunum.pdf` — 10 slaytlık PDF.
- `deliverables/2516016026_METEHAN_GEZER_Sunum.pptx` — düzenlenebilir PowerPoint.
- `deliverables/interactive_hashtag_network.html` — arama, topluluk filtresi ve düğüm ayrıntısı içeren etkileşimli alt ağ.

## Önemli son kontrol notları

- Temel ağ: 7.092 düğüm, 37.206 kenar, 538 bileşen; en büyük bileşen 5.731 düğüm.
- Louvain ve Leiden analizleri 10'ar tohumla çalıştırıldı; 100 null-model satırı vardır.
- Null-modeldeki düğüm-eşleme hatası düzeltildi: her null grafiği 7.092 düğüm içerir; etiketler iki kez sayılmaz.
- Zamansal analiz gerçek kayan pencere kullanır: 3 saat pencere, 1 saat adım; 46 pencere ve 45 NMI çifti.
- En büyük beş Louvain topluluğuna hashtag içeriklerine göre açıklayıcı isimler verildi.
- Genel ağ yol tahmini 100 kaynakla, null-model yol karşılaştırması ise gözlenen/null ağlarda eşit olmak üzere 20 kaynakla örneklenmiştir; raporda bu fark belirtilir.

## Gerekirse yeniden analiz çalıştırma

Anaconda Prompt'ta:

```cmd
conda activate hashtag-final
cd /d "C:\Users\gztme\OneDrive\Masaüstü\sosyal_ag_final"
python -m pip install -r requirements-final.txt
python finalize_project.py --null-models 100 --seeds 10
```

Bu tam analiz yeniden hesaplama yapar ve biraz sürebilir. Yalnızca mevcut `outputs/` sonuçlarından rapor, poster ve sunumu yeniden üretmek için:

```cmd
python render_final_deliverables.py
```

## GitHub'a yükleme

Önce `git status --short` ile değişen dosyaları kontrol et. `data/posts_hashtags_test_backup.csv`, `data/*.partial.csv`, `.env*`, API anahtarı, `node_modules/` ve `__pycache__/` yüklenmemelidir. `.gitignore` bu öğelerin çoğunu hariç tutar.

Önerilen son komutlar (proje klasöründeyken):

```cmd
git add README.md FINAL_KULLANIM.md finalize_project.py render_final_deliverables.py sosyal_ag_analizi_final.ipynb requirements-final.txt run_final_analysis.bat rerender_deliverables.bat collect_hashtags.py collect_historical_48h.mjs analyze_network.py package.json package-lock.json data/posts_hashtags_48h.csv data/posts_hashtags.csv outputs deliverables
git status --short
git commit -m "Finalize hashtag network analysis and deliverables"
git push
```

Komutlardaki dosya/klasör adlarının yerel klasörde bulunduğunu kontrol et. GitHub'da `.git/` klasörü yerelde kalır; bu klasör ZIP paketinin içinde yoktur ve silinmemelidir.
