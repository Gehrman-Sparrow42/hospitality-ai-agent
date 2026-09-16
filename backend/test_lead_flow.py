import os
os.environ["TESTING"] = "true"
import tempfile
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

import database
import config
from main import app
from security import security_guard


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database.init_db(path)
    monkeypatch.setattr(config, "DATABASE_PATH", path)
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def test_lead_detection_without_tag_semantic_fallback(temp_db):
    """
    Simulates the exact case where LLM answered with availability check promise
    but omitted the [REZERVASYON_BILGILERI_TAMAM: ...] bracket tag.
    """
    phone = "905559998877@c.us"
    security_guard.unblock_phone(phone)

    # Past history: customer previously mentioned dates
    database.save_message(phone, "user", "10-17 Eylül tarihleri arasında gelmek istiyoruz", db_path=temp_db)
    database.save_message(phone, "assistant", "Tarihleri not aldım, kaç kişi ve nasıl konaklayacaksınız?", db_path=temp_db)

    # Real-world LLM reply that omitted tag
    raw_llm_reply = (
        "Bilgilerinizi aldım. İki kişi çadır konaklayacaksınız ve 10-17 Eylül tarihleri arasında toplam 7 gün "
        "kalmayı planlıyorsunuz. Çadır konaklama ücreti günlük 1.500 TL'dir. 7 gün için toplam ücret: 10.500 TL. "
        "Müsaitlik durumunu kontrol edip kesin kayıt ve detaylar için birazdan size buradan dönüş sağlayacağız."
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_reservation_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = raw_llm_reply
        mock_alert.return_value = True

        with TestClient(app) as client:
            res = client.post("/webhook", json={
                "phone": phone,
                "message": "iki kişi olucaz ve cadır kurcaz toplam ücretimizi söyleyebilirmisiniz"
            })

            assert res.status_code == 200
            data = res.json()

            # Verify chat is muted
            assert data["is_muted"] is True
            assert data["action"] == "reservation_alert"
            assert "10-17 Eylül" in data["alert_details"]
            assert "iki kişi olucaz" in data["alert_details"]

            # Verify clean reply to customer without internal tags
            assert "Müsaitlik durumunu kontrol edip" in data["reply"]
            assert "[" not in data["reply"]

            # Verify database has marked lead and muted chat
            chat_status = database.get_chat_status(phone, db_path=temp_db)
            assert chat_status["is_muted"] == 1
            assert chat_status["is_reservation_lead"] == 1
            assert "iki kişi olucaz" in chat_status["lead_details"]

            # Now test follow up message while chat is muted:
            # Customer says: "tamam sizden haber bekliyorum rezervasyon için ne yapmamız gerekiyor"
            res_followup = client.post("/webhook", json={
                "phone": phone,
                "message": "tamam sizden haber bekliyorum rezervasyon için ne yapmamız gerekiyor"
            })
            assert res_followup.status_code == 200
            data_followup = res_followup.json()
            # Must remain muted and NOT auto-reply to disrupt human handover
            assert data_followup["is_muted"] is True
            assert data_followup["reply"] is None or data_followup["reply"] == ""


def test_exact_screenshot_dialogue(temp_db):
    """
    Tests the exact sequence in the user's screenshot:
    User asks what to do if available, assistant replies it will check availability shortly.
    """
    phone = "77528538599628@lid"
    security_guard.unblock_phone(phone)

    database.save_message(phone, "user", "iki kişi olucaz ve cadır kurcaz toplam ücretimizi söyleyebilirmisiniz", db_path=temp_db)
    database.save_message(phone, "assistant", "Çadır ücreti 10.500 TL dir.", db_path=temp_db)

    raw_llm_reply = (
        "Müsaitlik durumunu kontrol edip size kısa bir süre içinde buradan dönüş yapacağım. "
        "Eğer yerimiz varsa, rezervasyon işlemleri için gerekli bilgileri size ileteceğim. Beklediğiniz için teşekkür ederim."
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_reservation_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = raw_llm_reply
        mock_alert.return_value = True

        with TestClient(app) as client:
            res = client.post("/webhook", json={
                "phone": phone,
                "message": "-test tamam sizden haber bekliyorum rezervasyon için ne yapmamız gerekiyor müsaitlik varsa"
            })

            assert res.status_code == 200
            data = res.json()
            assert data["is_muted"] is True
            assert data["action"] == "reservation_alert"
            assert "iki kişi olucaz" in data["alert_details"]
            assert "rezervasyon için ne yapmamız gerekiyor" in data["alert_details"]
            assert mock_alert.called is True


def test_lead_detection_with_explicit_tag(temp_db):
    """
    Tests when LLM properly includes the [REZERVASYON_BILGILERI_TAMAM: ...] tag.
    """
    phone = "905551114455@c.us"
    security_guard.unblock_phone(phone)

    raw_llm_reply = (
        "Bilgilerinizi aldım. Müsaitlik durumunu kontrol edip kesin kayıt için birazdan buradan dönüş sağlayacağız. "
        "[REZERVASYON_BILGILERI_TAMAM: 20-25 Ağustos, 5 gün, 4 kişi aile motokaravan]"
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_reservation_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = raw_llm_reply
        mock_alert.return_value = True

        with TestClient(app) as client:
            res = client.post("/webhook", json={
                "phone": phone,
                "message": "20-25 Ağustos arası 4 kişilik aile motokaravan ile geleceğiz."
            })

            assert res.status_code == 200
            data = res.json()
            assert data["is_muted"] is True
            assert data["action"] == "reservation_alert"
            assert data["alert_details"] == "20-25 Ağustos, 5 gün, 4 kişi aile motokaravan"
            assert "[REZERVASYON" not in data["reply"]

            chat_status = database.get_chat_status(phone, db_path=temp_db)
            assert chat_status["is_muted"] == 1
            assert chat_status["is_reservation_lead"] == 1


def test_normal_inquiry_does_not_trigger_lead_or_mute(temp_db):
    """
    Ensures that standard camp questions (beach, rules, shade) do NOT trigger mute or lead alert.
    """
    phone = "905552226677@c.us"
    security_guard.unblock_phone(phone)

    raw_llm_reply = (
        "Kamp alanımızın ana giriş kapısı ana yola, sahile açılan kapıları ise doğrudan kumsala açılır. "
        "Aramızda herhangi bir yol veya işletme yoktur, denize sıfırdır."
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_reservation_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = raw_llm_reply

        with TestClient(app) as client:
            res = client.post("/webhook", json={
                "phone": phone,
                "message": "Denize mesafe ne kadar acaba?"
            })

            assert res.status_code == 200
            data = res.json()
            assert data["is_muted"] is False
            assert data["action"] is None
            assert "kumsala açılır" in data["reply"]

            # Verify NOT muted
            chat_status = database.get_chat_status(phone, db_path=temp_db)
            assert chat_status["is_muted"] == 0
            mock_alert.assert_not_called()


def test_kvkk_notice_on_first_interaction_only(temp_db):
    """
    Verifies that KVKK disclosure is attached on the first message,
    and NOT repeated on subsequent messages.
    """
    phone = "905553330011@c.us"
    security_guard.unblock_phone(phone)

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = "Kampımız İzmir Menderes'tedir."

        with TestClient(app) as client:
            # First interaction (empty history)
            res1 = client.post("/webhook", json={"phone": phone, "message": "Merhaba"})
            assert res1.status_code == 200
            data1 = res1.json()
            assert "KVKK'ya uygun olarak işlenmektedir" in data1["reply"]

            # Second interaction (past history exists)
            mock_query.return_value = "Çadır alanımız mevcuttur."
            res2 = client.post("/webhook", json={"phone": phone, "message": "Çadır getirebiliyor muyuz?"})
            assert res2.status_code == 200
            data2 = res2.json()
            assert "Çadır alanımız mevcuttur" in data2["reply"]
            # Must NOT repeat KVKK notice
            assert "KVKK'ya uygun olarak işlenmektedir" not in data2["reply"]


def test_cleanup_old_messages_10_days(temp_db):
    """
    Verifies that database.cleanup_old_messages deletes messages older than 10 days
    while preserving recent messages.
    """
    import sqlite3
    phone = "905557778899@c.us"

    # Insert a 15-day-old message and a current message directly
    with database.get_db(temp_db) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO messages (phone, role, content, created_at) VALUES (?, ?, ?, datetime('now', '-15 days'))",
            (phone, "user", "15 gun onceki eski mesaj")
        )
        c.execute(
            "INSERT INTO messages (phone, role, content, created_at) VALUES (?, ?, ?, datetime('now', '-2 days'))",
            (phone, "user", "2 gun onceki yeni mesaj")
        )

    # Clean messages older than 10 days
    pruned = database.cleanup_old_messages(days=10, db_path=temp_db)
    assert pruned == 1

    # Verify only recent message remains
    remaining = database.get_history(phone, limit=10, db_path=temp_db)
    assert len(remaining) == 1
    assert remaining[0]["content"] == "2 gun onceki yeni mesaj"


def test_payment_and_kapora_triggers_human_intervention(temp_db):
    """
    Verifies that asking for IBAN or kapora strictly mutes the bot,
    triggers intervention alert for the owner, and never gives an IBAN.
    """
    phone = "905553332211@c.us"
    security_guard.unblock_phone(phone)

    mock_llm_reply = (
        "Ödeme ve kapora işlemlerimiz yetkilimiz tarafından organize edilmektedir. "
        "Yetkilimize bilgi verdim, en kısa sürede dönüş sağlanacaktır. "
        "[YETKILI_DEVRET: Müşteri kapora ve IBAN bilgisi talep etti]"
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_intervention_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = mock_llm_reply
        mock_alert.return_value = True

        with TestClient(app) as client:
            res = client.post("/webhook", json={
                "phone": phone,
                "message": "Rezervasyon için nereye kapora atıyoruz? IBAN gönderir misiniz?"
            })

            assert res.status_code == 200
            data = res.json()
            assert data["is_muted"] is True
            assert data["action"] == "intervention_alert"
            assert "TR" not in data["reply"]
            assert "[YETKILI_DEVRET" not in data["reply"]
            mock_alert.assert_awaited_once()


def test_iban_leak_intercepted_by_sanitizer():
    """
    Verifies that even if an LLM hallucinates an IBAN, the security sanitizer
    intercepts it, strips the IBAN, and overrides with safe human handover.
    """
    hallucinated_reply = "Kapora için TR12 3456 7890 1234 5678 9012 34 nolu hesaba 1.000 TL atabilirsiniz."
    sanitized = security_guard.sanitize_output(hallucinated_reply)

    assert "TR12" not in sanitized
    assert "Ödeme, kapora ve hesap işlemlerimiz doğrudan işletme yetkilimiz tarafından" in sanitized
    assert "[YETKILI_DEVRET:" in sanitized


def test_spaced_tag_stripped_completely(temp_db):
    """
    Verifies that tags with leading/trailing spaces like '[ YETKILI_DEVRET: ... ]'
    are completely stripped from the customer reply.
    """
    phone = "905559990011@c.us"
    security_guard.unblock_phone(phone)

    mock_llm_reply = (
        "Ödeme, kapora ve hesap işlemlerimiz doğrudan işletme yetkilimiz tarafından güvenli şekilde yürütülmektedir.\n\n"
        "[ YETKILI_DEVRET: Müşteri kapora/ödeme/IBAN bilgisi talep etti ]"
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_intervention_alert", new_callable=AsyncMock):
        mock_query.return_value = mock_llm_reply

        with TestClient(app) as client:
            res = client.post("/webhook", json={
                "phone": phone,
                "message": "nereye para atıyoruz"
            })

            assert res.status_code == 200
            data = res.json()
            assert "YETKILI_DEVRET" not in data["reply"]
            assert "[" not in data["reply"]
            assert "]" not in data["reply"]
            assert data["is_muted"] is True


def test_price_inquiry_does_not_mute_until_explicit_reservation(temp_db):
    """
    Validates that a customer inquiring about prices/bungalows/tents is NOT muted,
    and only becomes muted when they explicitly ask to make/set up a reservation.
    """
    phone = "905556667788@c.us"
    security_guard.unblock_phone(phone)

    price_reply = (
        "Kendi çadırınızla gelirseniz günlük 1.500 TL'dir. Tesisimizde kiralık çadır veya bungalov bulunmamaktadır. "
        "Fiyatlarımız bu şekildedir. Rezervasyon oluşturmak veya yer ayırtmak isterseniz yardımcı olabilirim."
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_reservation_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = price_reply

        with TestClient(app) as client:
            # 1. Customer asks prices and options (should NOT mute)
            res1 = client.post("/webhook", json={
                "phone": phone,
                "message": "Ben sadece aracımla geleceğim sizin bungalov ve çadır ikisini de öğrenmek istiyorum"
            })
            assert res1.status_code == 200
            data1 = res1.json()
            assert data1["is_muted"] is False
            assert data1["action"] is None
            mock_alert.assert_not_called()

            chat_status1 = database.get_chat_status(phone, db_path=temp_db)
            assert chat_status1["is_muted"] == 0
            assert chat_status1["is_reservation_lead"] == 0

            # 2. Customer continues asking another question (food/breakfast - should still work without mute)
            mock_query.return_value = "Kamp alanımızda yemek veya kahvaltı servisi bulunmamaktadır."
            res2 = client.post("/webhook", json={
                "phone": phone,
                "message": "yemek konusunu nasıl halledeceğiz kahvaltı falan çıkıyor mu"
            })
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2["is_muted"] is False
            assert "yemek veya kahvaltı" in data2["reply"]

            # 3. Customer now explicitly requests booking (MUST trigger reservation alert and mute)
            reservation_confirm_reply = (
                "Harika, rezervasyon talebinizi aldım. Müsaitlik durumunu kontrol edip kesin rezervasyon teyidi için "
                "yetkilimiz kısa bir süre içinde size buradan dönüş sağlayacaktır. "
                "[REZERVASYON_BILGILERI_TAMAM: 2 kişi çadır, hafta sonu]"
            )
            mock_query.return_value = reservation_confirm_reply
            mock_alert.return_value = True

            res3 = client.post("/webhook", json={
                "phone": phone,
                "message": "Tamam o zaman 2 kişi için çadır rezervasyonu ayarlayalım"
            })
            assert res3.status_code == 200
            data3 = res3.json()
            assert data3["is_muted"] is True
            assert data3["action"] == "reservation_alert"
            assert mock_alert.called is True

            chat_status3 = database.get_chat_status(phone, db_path=temp_db)
            assert chat_status3["is_muted"] == 1
            assert chat_status3["is_reservation_lead"] == 1


def test_advantage_hook_and_explanation_flow(temp_db):
    """
    Tests the flow where:
    1. Customer asks price -> bot answers and asks if customer wants to hear advantages.
    2. Customer says 'olur' -> bot explains no electricity fee, free amenities, no surprise fee. Chat stays UNMUTED.
    3. Customer says 'tamam rezervasyon yapalım' -> bot confirms, triggers lead, and mutes.
    """
    phone = "905554443322@c.us"
    security_guard.unblock_phone(phone)

    price_reply = (
        "3 gün çadır konaklama toplam 4.500 TL tutmaktadır. "
        "Dilerseniz kampımızı bölgedeki diğer kamplardan ayıran avantajlarımızdan ve fiyata nelerin dahil olduğundan da kısaca bahsedebilirim, duymak ister misiniz?"
    )

    advantage_reply = (
        "Kampımızda standart elektrik ve su kullanımı için kesinlikle ekstra bir ücret alınmaz. "
        "Sıcak su duşları, tuvaletler, ortak buzdolapları ve çamaşır makinesi kullanımı alan ücretine dahildir. "
        "Kişi başı veya otopark ücreti yoktur, tüm fiyatlara KDV dahildir. "
        "Yetkilimizle ücret kesinleştirildikten sonra sonradan asla sürpriz veya ekstra bir ücret çıkarılmaz."
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_reservation_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = price_reply

        with TestClient(app) as client:
            # 1. Price inquiry
            res1 = client.post("/webhook", json={
                "phone": phone,
                "message": "3 gün çadır ne kadar tutar?"
            })
            assert res1.status_code == 200
            data1 = res1.json()
            assert data1["is_muted"] is False
            assert "avantajlarımızdan" in data1["reply"]

            # 2. Customer accepts hearing advantages
            mock_query.return_value = advantage_reply
            res2 = client.post("/webhook", json={
                "phone": phone,
                "message": "olur anlatın lütfen avantajlar neler"
            })
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2["is_muted"] is False
            assert "elektrik" in data2["reply"]
            assert "sürpriz veya ekstra" in data2["reply"]

            # 3. Customer decides to book
            mock_query.return_value = (
                "Harika, rezervasyon talebinizi aldım. Müsaitlik durumunu kontrol edip yetkilimiz dönüş yapacaktır. "
                "[REZERVASYON_BILGILERI_TAMAM: 3 gün çadır]"
            )
            mock_alert.return_value = True
            res3 = client.post("/webhook", json={
                "phone": phone,
                "message": "Çok iyiymiş tamam rezervasyon ayarlayalım o zaman"
            })
            assert res3.status_code == 200
            data3 = res3.json()
            assert data3["is_muted"] is True
            assert data3["action"] == "reservation_alert"
            assert mock_alert.called is True


def test_mixed_group_transfers_to_human_instead_of_rejecting(temp_db):
    """
    Tests that when a mixed friend group asks for accommodation (e.g. 1 erkek 4 kız),
    the assistant does NOT flat-out reject them with 'kabul edemiyoruz'.
    Instead, it refers them to the camp coordinator, triggers an intervention alert,
    and mutes the bot so the coordinator can evaluate and close the deal.
    """
    phone = "905553334455@c.us"
    security_guard.unblock_phone(phone)

    mixed_group_reply = (
        "Tesisimiz sakinlik ve aile konseptiyle hizmet vermektedir; bu tür karma grup konaklama taleplerinde "
        "uygunluk ve kontenjan durumu doğrudan kamp koordinatörümüz tarafından değerlendirilmektedir. "
        "Bilgilerinizi koordinatörümüze ilettim, en kısa sürede size buradan dönüş sağlayacaktır. "
        "[YETKILI_DEVRET: Karma / Arkadaş Grubu Konaklama Talebi (1 erkek 4 kız, toplam 5 kişi, 5 gün)]"
    )

    with patch("main.query_llm", new_callable=AsyncMock) as mock_query, \
         patch("notifier.send_intervention_alert", new_callable=AsyncMock) as mock_alert:
        mock_query.return_value = mixed_group_reply
        mock_alert.return_value = True

        with TestClient(app) as client:
            res = client.post("/webhook", json={
                "phone": phone,
                "message": "1 erkek 4 kız olacağız toplam 5 kişi 5 gün kalacağız"
            })
            assert res.status_code == 200
            data = res.json()

            # Verify no rude rejection
            assert "kabul edemiyoruz" not in data["reply"]
            assert "bekar misafir kabul" not in data["reply"]
            assert "koordinatörümüz" in data["reply"]

            # Verify internal tags stripped from user view
            assert "YETKILI_DEVRET" not in data["reply"]
            assert "[" not in data["reply"]

            # Verify human intervention alert triggered and bot muted
            assert data["is_muted"] is True
            assert data["action"] == "intervention_alert"
            assert "1 erkek 4 kız" in data["alert_details"]
            mock_alert.assert_awaited_once()

            # Verify chat is muted in database
            chat_status = database.get_chat_status(phone, db_path=temp_db)
            assert chat_status["is_muted"] == 1






