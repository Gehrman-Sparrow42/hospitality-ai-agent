# 🚀 VDS / Cloud Sunucuya Dağıtım (Deployment) Rehberi (API Key & Docker)

Bu proje, sunucuda ağır modeller (Ollama) çalıştırmaya gerek kalmadan, doğrudan **OpenAI, Groq, OpenRouter veya Gemini API anahtarı** ile çalışacak şekilde optimize edilmiştir.

---

## 1. VDS Sunucu Donanım Gereksinimleri (API Modu ile)

Modeli sunucu içinde çalıştırmadığınız (API kullandığınız) için pahalı sunuculara **asla gerek yoktur**:

| Kurulum Türü | Gerekli RAM | CPU | Aylık Sunucu Maliyeti |
| :--- | :--- | :--- | :--- |
| **Cloud API Modu (Önerilen)** | **1 GB - 2 GB RAM** | 1-2 vCPU | **~€3 - €5 / ay** (Cenuta, Hetzner CX22) |
| *Lokal Ollama Modu (Alternatif)* | *8 GB - 16 GB RAM* | *4-8 vCPU* | *~€10 - €25 / ay* |

> [!TIP]
> **En Hızlı & En Ucuz Seçenekler:**
> 1. **Groq API:** Neredeyse ücretsiz veya çok ucuz, saniyede 300+ kelime üretir (`llama-3.3-70b-versatile`).
> 2. **OpenAI API (`gpt-4o-mini`):** 1 milyon token sadece ~$0.15 (aylık yoğun WhatsApp mesajlaşmasında bile birkaç TL tutar).

---

## 2. Sunucuda Kurulum (Adım Adım)

### Adım 1: Sunucunuza SSH ile Bağlanın
```bash
ssh root@SUNUCU_IP_ADRESINIZ
```

### Adım 2: Docker Kurun (Tek Komut)
```bash
curl -fsSL https://get.docker.com | sh
```

### Adım 3: Projeyi Sunucuya Çekin
```bash
git clone <GITHUB_VEYA_REPO_LINKINIZ> /root/whatsapp-camp-bot
cd /root/whatsapp-camp-bot
```

### Adım 4: `.env` Dosyanızı Oluşturun ve API Key'inizi Ekleyin
```bash
cp .env.example .env
nano .env
```
`.env` dosyanızda API anahtarınızı girin:
```env
# Örnek OpenAI kullanımı:
LLM_PROVIDER=openai
LLM_API_KEY=sk-proj-BURAYA_OPENAI_KEYINIZI_YAZIN
LLM_MODEL=gpt-4o-mini

# VEYA Örnek Groq kullanımı:
# LLM_PROVIDER=groq
# LLM_API_KEY=gsk_BURAYA_GROQ_KEYINIZI_YAZIN
# LLM_MODEL=llama-3.3-70b-versatile
```
Kaydedip çıkmak için: `Ctrl + O`, `Enter`, `Ctrl + X`.

### Adım 5: Docker ile Sistemi Başlatın
```bash
docker compose up -d --build
```
Bu komut sunucunuzda sadece **Backend (FastAPI)** ve **WhatsApp Köprüsünü (Chromium)** ayağa kaldırır. Toplam RAM tüketimi sadece ~400 MB civarındadır.

---

## 3. WhatsApp Hesabını Bağlama (QR Kod)

1. Tarayıcınızdan sunucunuzun IP adresine gidin:
   ```
   http://SUNUCU_IP_ADRESINIZ:8000
   ```
2. **"Bağlantı"** sekmesindeki QR kodu işletme telefonundaki WhatsApp'tan okutun.
3. **"Alarm (ntfy)"** sekmesindeki QR kodu telefonunuza okutup tek tıkla abone olun.
4. Test mesajı atarak sistemin yanıt verdiğini ve mobil bildirimlerin çaldığını görün!

---

## 4. Antigravity'yi VDS Üzerinde Kullanabilir miyim?

**Evet! Bunun için 2 harika yönteminiz var:**

### Yöntem 1 — Doğrudan Kendi Bilgisayarınızdaki Antigravity ile VDS'e Bağlanma (En Rahat Yöntem)
Kendi bilgisayarınızda açık olan Antigravity IDE üzerinden VDS'e bağlanıp kod yazabilirsiniz:
- Antigravity IDE'de sol alttaki Remote bağlantı simgesine veya `SSH: Connect to Host` seçeneğine tıklayın.
- `ssh root@SUNUCU_IP_ADRESINIZ` yazıp bağlanın.
- VDS'in `/root/whatsapp-camp-bot` klasörünü Antigravity içinde açın.
- Ben (Antigravity Asistanınız) doğrudan VDS'in içindeki dosyaları görüp terminal komutlarını canlı olarak çalıştırabilirim!

### Yöntem 2 — VDS Terminalinde Antigravity CLI (`agy`) Kullanma
Eğer VDS terminali içinde doğrudan yapay zeka ajan komutlarını çalıştırmak isterseniz:
- VDS sunucunuza Antigravity CLI kurarak terminal üzerinden `agy` komutlarıyla sohbet edebilir ve görevler verebilirsiniz.
