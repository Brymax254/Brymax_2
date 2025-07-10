# automatic.py

import os
import django
from django.apps import apps
from django.db import connections, transaction
from django.db.utils import OperationalError, ProgrammingError

# Correct path to your Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()

def push_data_to_online():
    local_db = 'default'
    online_db = 'online'

    all_models = apps.get_models()

    for model in all_models:
        model_name = model.__name__
        try:
            local_data = model.objects.using(local_db).all()

            if not local_data.exists():
                print(f"⏩ Skipping {model_name}: no data found.")
                continue

            print(f"🔄 Syncing model: {model_name} ({local_data.count()} records)...")

            try:
                model.objects.using(online_db).all().delete()
            except Exception as e:
                print(f"⚠️ Could not delete existing online data for {model_name}: {e}")

            with transaction.atomic(using=online_db):
                for obj in local_data:
                    obj.pk = None
                    obj.save(using=online_db)

            print(f"✅ Done syncing: {model_name}")

        except (OperationalError, ProgrammingError) as db_err:
            print(f"❌ Skipping {model_name}: {db_err}")
        except Exception as e:
            print(f"❌ Error syncing {model_name}: {e}")

if __name__ == '__main__':
    push_data_to_online()
