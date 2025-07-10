import os
import sys
import django
from django.core.management import call_command
from django.core.exceptions import ImproperlyConfigured

def migrate_all_apps():
    # Use production settings if on Render, otherwise fall back to base settings
    settings_module = 'config.settings.production' if 'RENDER' in os.environ else 'config.settings.base'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)

    try:
        django.setup()
    except ImproperlyConfigured as e:
        print(f"❌ Improperly configured settings: {e}")
        sys.exit(1)

    print("\n🔄 Making migrations for all apps...")
    try:
        call_command('makemigrations')
    except Exception as e:
        print(f"❌ Failed to make migrations: {e}")
        sys.exit(1)

    print("\n✅ Applying all migrations...")
    try:
        call_command('migrate')
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

    print("\n🚀 All migrations applied successfully!")

if __name__ == '__main__':
    migrate_all_apps()
