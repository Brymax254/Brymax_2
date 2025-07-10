from django.db import models
from django.contrib.auth import get_user_model
from apps.client.models import Client

class Payment(models.Model):
    client  = models.ForeignKey(Client, on_delete=models.CASCADE)
    amount  = models.DecimalField(max_digits=9, decimal_places=2)
    ref     = models.CharField(max_length=100, unique=True)
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f'{self.ref} - {self.amount}'
