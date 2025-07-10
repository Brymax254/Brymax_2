import os
import django
from django.core.management import call_command

def migrate_all_apps():
    # Set your Django settings module (adjust as needed)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
    django.setup()

    print("\n🔄 Making migrations for all apps...")
    call_command('makemigrations')

    print("\n✅ Applying all migrations...")
    call_command('migrate')

    print("\n🚀 All migrations applied successfully!")

if __name__ == '__main__':
    migrate_all_apps()
