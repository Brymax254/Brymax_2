from django.db import migrations

def unify_tracking_field(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")

    for payment in Payment.objects.all():
        # If pesapal_reference was used, copy it to pesapal_tracking_id
        if getattr(payment, "pesapal_reference", None) and not payment.pesapal_tracking_id:
            payment.pesapal_tracking_id = payment.pesapal_reference
            payment.save(update_fields=["pesapal_tracking_id"])

def rollback(apps, schema_editor):
    # Rollback: copy back to pesapal_reference if needed
    Payment = apps.get_model("payments", "Payment")

    for payment in Payment.objects.all():
        if payment.pesapal_tracking_id and not getattr(payment, "pesapal_reference", None):
            payment.pesapal_reference = payment.pesapal_tracking_id
            payment.save(update_fields=["pesapal_reference"])

class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0018_payment_days_alter_payment_confirmation_code_and_more.py"),  # replace with last migration name
    ]

    operations = [
        migrations.RunPython(unify_tracking_field, rollback),
    ]
