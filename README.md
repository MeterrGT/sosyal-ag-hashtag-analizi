# Sosyal Ağ Analizi — Bluesky Hashtag Ağı

**Öğrenci:** Metehan Gezer  
**Öğrenci No:** 2516016026  
**Program:** Büyük Veri Analistliği  
**Dönem:** 2026-2027 Güz

## 1. Projenin Amacı

Bu projede Bluesky sosyal medya akışındaki Türkçe gönderilerden hashtag ağı oluşturulmaktadır.

Araştırma sorusu:
- Gündem toplulukları saatler içinde ne kadar kararlıdır?
- Hangi hashtag'ler farklı gündem topluluklarını birbirine bağlamaktadır?

## 2. Veri ve Ağ Modeli

- **Veri kaynağı:** Bluesky Jetstream arşivi
- **Zaman aralığı:** 24–26 Ekim 2026, 48 saat
- **Düğüm:** Hashtag
- **Kenar:** Aynı gönderide birlikte geçen hashtag'ler
- **Gizlilik:** Gönderi metinleri ve kullanıcı kimlikleri saklanmamaktadır.

## 3. Veri Toplama

Arşivden elde edilen veriler zaman aralığı ve dil koşullarına göre filtrelenmiştir.

- İşlenen olay: 8.185.391
- İncelenen 48 saatlik aralıktaki gönderiler: 7.476.367
- Türkçe gönderiler: 38.474
- Hashtag içeren kaydedilmiş gönderiler: 7.658

## 4. İlk Ağ Analizi Sonuçları

| Ölçüm | Sonuç |
|---|---:|
| Düğüm sayısı | 7.092 |
| Kenar sayısı | 37.206 |
| Ağ yoğunluğu | 0,00148 |
| Bağlantılı bileşen sayısı | 538 |
| En büyük bileşendeki düğüm sayısı | 5.731 |
| En büyük bileşende ortalama en kısa yol | 3,355 |
| En büyük bileşenin çapı | 14 |
| Ortalama kümelenme katsayısı | 0,803 |

En kısa yol ve çap ölçümleri yalnızca en büyük bağlantılı bileşen üzerinden hesaplanmıştır.

## 5. Dosyalar

- `collect_hashtags.py`: Canlı akıştan hashtag toplama
- `collect_historical_48h.mjs`: Geçmiş 48 saatlik arşivi toplama
- `analyze_network.py`: Ağ oluşturma ve temel analiz
- `data/`: Toplanan hashtag verileri
- `outputs/edges.csv`: Kenar listesi
- `outputs/hashtags.graphml`: Ağın GraphML dosyası
- `outputs/basic_metrics.json`: Temel ağ ölçüleri
- `outputs/degree_distribution.png`: Derece dağılım grafiği
- `outputs/top_degree.csv`: En yüksek dereceye sahip hashtag'ler

## 6. Kurulum ve Çalıştırma

Python bağımlılıklarını yüklemek için:

```bash
python -m pip install -r requirements.txt