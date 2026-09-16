import os
import tempfile
import unittest
import database

class TestDatabaseAndLogic(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_file.name
        self.temp_file.close()
        database.init_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_database_lifecycle(self):
        phone = "905551234567@c.us"
        
        # 1. Initial state
        self.assertEqual(database.get_history(phone, limit=6, db_path=self.db_path), [])

        # 2. Insert messages
        database.save_message(phone, "user", "Yarın giriş saat kaçta?", db_path=self.db_path)
        database.save_message(phone, "assistant", "Giriş 10:00 - 14:00 arasındadır.", db_path=self.db_path)
        database.save_message(phone, "user", "Çadır veriyor musunuz?", db_path=self.db_path)
        database.save_message(phone, "assistant", "Kendi çadırınızı getirmelisiniz.", db_path=self.db_path)

        # 3. Retrieve history with limit = 2 (should get the 2 most recent messages in chronological order)
        recent_history = database.get_history(phone, limit=2, db_path=self.db_path)
        self.assertEqual(len(recent_history), 2)
        self.assertEqual(recent_history[0]["role"], "user")
        self.assertEqual(recent_history[0]["content"], "Çadır veriyor musunuz?")
        self.assertEqual(recent_history[1]["role"], "assistant")
        self.assertEqual(recent_history[1]["content"], "Kendi çadırınızı getirmelisiniz.")

        # 4. Retrieve full history with limit = 6
        full_history = database.get_history(phone, limit=6, db_path=self.db_path)
        self.assertEqual(len(full_history), 4)
        self.assertEqual(full_history[0]["content"], "Yarın giriş saat kaçta?")

        # 5. Clear history
        deleted = database.clear_history(phone, db_path=self.db_path)
        self.assertEqual(deleted, 4)
        self.assertEqual(database.get_history(phone, limit=6, db_path=self.db_path), [])

if __name__ == "__main__":
    unittest.main()
