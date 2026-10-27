# Sosyal Ağ Analizi — başlangıç paketi

Bu başlangıç paketi Bluesky Jetstream'den Türkçe gönderilerdeki hashtag'leri toplamak ve ilk hashtag eş-oluşum ağını kurmak içindir.

## Gizlilik ve veri tanımı

- Ağ düğümü: hashtag.
- Kenar: iki hashtag'in aynı gönderide birlikte görünmesi.
- Kenar ağırlığı: birlikte geçme sayısı.
- Kaydedilen satır: UTC zaman damgası + hashtag listesi.
- Ham gönderi metni ve kullanıcı kimliği CSV'ye yazılmaz. Dil tespiti ve hashtag çıkarımı için metin yalnızca bellekte işlenir.

## Kurulum (Anaconda Prompt / terminal)

```bash
cd sosyal_ag_baslangic
python -m pip install -r requirements.txt
```

## Veri toplama

Varsayılan süre 48 saattir:

```bash
python collect_hashtags.py
```

Daha kısa bir test için:

```bash
# Windows PowerShell
$env:COLLECT_HOURS="0.05"
python collect_hashtags.py
```

Bilgisayar uykuya geçerse veya internet kesilirse veri akışı kaçabilir. Program bağlantı kopunca yeniden bağlanır; ancak bağlantı yokken kaçan gönderileri bu basit canlı akış toplayıcısı geriye dönük tamamlamaz. Gerçek çalıştırma süresini ve sınırlılıkları raporda dürüstçe belirtin.

## İlk ağ ve ölçüler

CSV'de veri biriktikten sonra:

```bash
python analyze_network.py
```

`outputs/` içine kenar listesi CSV, GraphML, temel metrik JSON'u, derece tablosu ve log-log derece grafiği yazar. Henüz Louvain/Leiden karşılaştırması, 100 null model, üç saatlik pencereler, NMI/ARI veya betweenness analizi üretmez; bunlar sonraki aşamalardır.

## Önemli

Bu kod bir başlangıçtır, tamamlanmış ödev değildir. Jetstream bağlantısını, toplanan satırları ve ağ boyutunu kontrol edin. Ödev kartındaki veri toplama koşullarını ve tüm ölçümlerin açıklamasını raporda belirtin. Yapay zekâ yardımı kullanıldığını README'de beyan edin ve derste açıklayamadığınız sonuçları teslim etmeyin.
