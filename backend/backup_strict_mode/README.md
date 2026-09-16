# Yapay Zeka Modları ve Yedekler Rehberi

Bu klasör, yapay zekanın önceki **"Sıfır Halüsinasyon / Katı Kurumsal Mod"** (Strict Production Mode) ayarlarını saklar.

---

## 📁 Dosyalar

1. **[`config_strict.py`](file:///c:/Tools/whatsapp-camp-bot-poc/backend/backup_strict_mode/config_strict.py)**:
   * `OLLAMA_TEMPERATURE = 0.1` (Tamamen katı, yaratıcılık kapalı).
   * Kesin yasaklar: Şiir, kod, genel sohbet, flört yasak.
   * Bilgi bankasında yazmayan her şeye *"Bu konuyu kamp koordinatörümüze iletiyorum"* der.

2. **[`security_strict.py`](file:///c:/Tools/whatsapp-camp-bot-poc/backend/backup_strict_mode/security_strict.py)**:
   * Genel sohbet girişimlerini (`sohbet edelim`, `muhabbet edelim` vb.) doğrudan keser.
   * Çıktı filtresinde metinde olmayan otel, havuz vb. uydurmaları anında koordinatör cevabına çevirir.

---

## 🔄 Eski Katı Moda Nasıl Geri Dönülür?

Eğer gelecekte kampa gerçek müşteriler gelmeye başladığında yapay zekanın **asla doğaçlama yapmamasını**, yalnızca koordinatöre yönlendirmesini isterseniz:
1. `backend/backup_strict_mode/config_strict.py` dosyasındaki ayarları `backend/config.py` içine kopyalamanız veya bana *"Eski katı kurumsal moda geri dönelim"* demeniz yeterlidir!
