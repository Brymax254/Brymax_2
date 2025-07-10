from django.db import models

class Client(models.Model):
    full_name = models.CharField(max_length=120)
    phone     = models.CharField(max_length=20)
    email     = models.EmailField(unique=True)

    def __str__(self):
        return self.full_name
