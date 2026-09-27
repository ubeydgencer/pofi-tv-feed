# pofi-tv-feed

Pofi TV uygulamasının video listesi ve web sayfaları.

- `channels.json` – elle doğrulanmış çocuk kanalları (resmi kanal, onay rozeti, abone sayısıyla eşleştirildi)
- `blocklist.json` – başlıkta geçerse videoyu eleyen kelimeler
- `build_feed.py` – YouTube Data API v3 ile `site/feed.json` üretir (sadece stdlib)
- `site/` – GitHub Pages: kısa tanıtım sayfası ve `feed.json` (https://ubeydgencer.com/pofi-tv-feed/feed.json)
- Gizlilik politikası ana sitede: https://ubeydgencer.com/pofi-tv/gizlilik
- `.github/workflows/feed.yml` – 6 saatte bir çalışır, testleri koşar, Pages'e yayınlar

## Kurulum
1. Google Cloud'da YouTube Data API v3'ü açın, API anahtarı oluşturun ve anahtarı **sadece YouTube Data API v3** ile kısıtlayın.
2. Repo → Settings → Secrets and variables → Actions → `YOUTUBE_API_KEY`.
3. Repo → Settings → Pages → Source: **GitHub Actions**.
4. Actions → "Build feed" → Run workflow.

Yerelde deneme: `.env` dosyasına `YOUTUBE_API_KEY=...` yazıp `python3 build_feed.py`.
Kanal eklemek/çıkarmak için sadece `channels.json` düzenlenir; uygulama güncellemesi gerekmez.
