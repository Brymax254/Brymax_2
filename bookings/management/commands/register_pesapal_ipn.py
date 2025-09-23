from django.core.management.base import BaseCommand
from bookings.utils.pesapal import register_pesapal_ipn

class Command(BaseCommand):
    help = "Registers IPN URL with Pesapal and retrieves the notification_id"

    def handle(self, *args, **options):
        self.stdout.write("Registering IPN URL with Pesapal...")
        try:
            result = register_pesapal_ipn()
            ipn_id = result.get("ipn_id")
            if not ipn_id:
                self.stderr.write(f"❌ Failed to register IPN: {result}")
                return
            self.stdout.write(self.style.SUCCESS(f"✅ Success! IPN ID: {ipn_id}"))
            self.stdout.write("👉 Copy this into your .env as PESAPAL_NOTIFICATION_ID")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error: {e}"))
