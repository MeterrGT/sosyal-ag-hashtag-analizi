# Sosyal Medyada Hashtag Ağı — Final Projesi

**Öğrenci:** Metehan Gezer · **Öğrenci no:** 2516016026  
**Program:** Büyük Veri Analistliği · **Ders:** Sosyal Ağ Analizi

## Araştırma sorusu

Gündem toplulukları saatler içinde ne kadar kararlıdır? Hangi hashtag'ler farklı gündem topluluklarını birbirine bağlamaktadır?

## Veri ve ağ modeli

- **Kaynak:** Bluesky Jetstream v2 arşivi.
- **Zaman aralığı:** 24 Ekim 2026 22:05:33 UTC – 26 Ekim 2026 22:05:22 UTC (yaklaşık 48 saat).
- **Kaydedilen gönderi:** 7.658 Türkçe hashtag'li gönderi.
- **Gizlilik:** CSV'de yalnızca UTC zaman damgası ve hashtag listesi vardır; ham gönderi metni ve kullanıcı kimliği kaydedilmez.
- **Düğüm:** normalize edilmiş hashtag.
- **Kenar:** aynı gönderide birlikte görülen iki farklı hashtag.
- **Kenar ağırlığı:** hashtag çiftinin birlikte görüldüğü gönderi sayısı; ağ yönsüzdür.

## Temel bulgular

| Ölçüm | Sonuç |
|---|---:|
| Düğüm | 7.092 |
| Kenar | 37.206 |
| Yoğunluk | 0,001480 |
| Bağlı bileşen | 538 |
| En büyük bileşen | 5.731 düğüm |
| Ortalama kümelenme katsayısı | 0,8032 |
| Derece benzeşimi | -0,1358 |
| En büyük bileşende 100 kaynakla örneklemeli ortalama yol | 3,380 |
| Örneklem çapı alt sınırı | 11 |

### Merkeziyet ve topluluklar

En yüksek dereceye sahip hashtag'ler `#türkiye` (1.587), `#gündem` (1.219) ve `#haber` (1.155) olmuştur. Bu ölçü bir hashtag'in kaç farklı komşu hashtag'le bağlantılı olduğunu gösterir; gönderi sayısı veya kullanıcı sayısıyla aynı şey değildir.

- **Louvain:** 589 topluluk; 10 tohumdaki ortalama çiftli NMI 0,8763; ortalama ağırlıklı modülerlik 0,5928.
- **Leiden:** 583 topluluk; 10 tohumdaki ortalama çiftli NMI 0,8889; ortalama ağırlıklı modülerlik 0,5952.
- **İçeriğe göre adlandırılan en büyük topluluklar:** Türkiye gündemi ve siyaset; dış politika ve güncel haber akışı; hukuk, protesto ve yerel gündem; uluslararası haber ve dünya siyaseti; Türkiye medyası ve futbol gündemi. Bu etiketler toplulukların en sık görülen hashtag'lerini özetler; her düğümün tek bir konuya ait olduğunu garanti etmez.

### Zamansal analiz

48 saat 3 saat uzunluğunda ve 1 saat adımlı **örtüşen kayan pencerelere** ayrılmıştır: 46 pencere ve 45 ardışık-pencere NMI karşılaştırması. Ortalama NMI 0,8447'dir (min. 0,6728; maks. 0,9673). Pencereler iki saat örtüştüğü için yüksek NMI değerleri bu örtüşme bağlamında yorumlanmalıdır.

### Null model ve derece dağılımı

100 configuration-model ağıyla karşılaştırmada gözlenen kümelenme 0,8032, null ortalaması 0,0736 (z=543,770); örneklemeli ortalama yol 3,1251, null ortalaması 3,1680 (z=-0,599); ağırlıksız Louvain modülerliği 0,6312, null ortalaması 0,2604 (z=245,861) bulunmuştur. Null grafiği düğümleri özgün hashtag düğümleriyle bire bir eşleştirilmiştir; self-loop ve çoklu kenarlar sadeleştirmede kaldırıldığından model kenar sayısı gözlenen ağla aynı olmak zorunda değildir. Yol uzunluğu null karşılaştırması, gözlenen ve null ağlarda 20 kaynak düğümle örneklenmiştir.

Derece dağılımı için power-law modeli ve alternatifleri karşılaştırılmıştır: alpha=2,311, xmin=33; power-law ile exponential karşılaştırmasında R=84,984 ve p=2,19e-5; power-law ile lognormal karşılaştırmasında R=-0,007 ve p=0,929. Sonuç, power-law'ın exponential alternatife göre daha iyi olduğunu destekler; lognormal ile karşılaştırma ise aralarındaki fark için belirgin kanıt vermez. Bu nedenle derece dağılımı tek başına kesin biçimde “kuvvet yasasıdır” diye yorumlanmamalıdır.

## Dosyalar

- `data/posts_hashtags_48h.csv`: final analizinde kullanılan veri (UTC zaman damgası ve hashtag listesi).
- `collect_historical_48h.mjs`: Jetstream arşivinden geçmiş 48 saatlik veriyi toplama kodu.
- `collect_hashtags.py`: canlı akıştan hashtag toplama kodu.
- `finalize_project.py`: tekrarlanabilir final analiz iş akışı.
- `render_final_deliverables.py`: kaydedilmiş analiz çıktılarından rapor, poster ve sunumu yeniden üretme.
- `sosyal_ag_analizi_final.ipynb`: yöntemi ve çalıştırma adımlarını gösteren Jupyter defteri.
- `outputs/`: kenar listesi, GraphML, merkeziyet tabloları, Louvain/Leiden bölümleri, NMI, null model ve grafikler.
- `deliverables/`: 8 sayfalık rapor PDF, A3 poster PDF, 10 slaytlık PDF/PPTX ve etkileşimli ağ HTML'i.

## Yeniden üretilebilirlik

Windows/Anaconda ortamında Python 3.13 kullanılması önerilir:

```cmd
conda activate hashtag-final
python -m pip install -r requirements-final.txt
python finalize_project.py --null-models 100 --seeds 10
```

Kaydedilmiş analiz çıktılarından yalnızca rapor/poster/sunumu yeniden üretmek için:

```cmd
python render_final_deliverables.py
```

Etkileşimli HTML, `vis-network` kütüphanesini CDN'den yükler ve görüntülemek için internet bağlantısı gerektirir.

## Sınırlılıklar ve etik

Bluesky örneklemi tüm sosyal medya kullanıcılarını veya Türkiye nüfusunu temsil etmez. Türkçe dil filtresi hata içerebilir. Aynı gönderide hashtag'lerin birlikte geçmesi kullanıcı etkisini veya nedenselliği kanıtlamaz. Merkeziyet ve bazı yol ölçüleri büyük ağ nedeniyle tekrarlanabilir örnekleme ile yaklaşık hesaplanmıştır. Yalnızca açık veriye erişilmiş; ham gönderi metinleri ve hesap kimlikleri kalıcı olarak saklanmamıştır.

## Yapay zekâ beyanı

Kod geliştirme, hata ayıklama ve rapor/sunum dilinin düzenlenmesinde yapay zekâ araçlarından destek alınmıştır. Analiz sonuçları, yöntemler ve sınırlılıklar bu depodaki çıktılarla kontrol edilebilir.
