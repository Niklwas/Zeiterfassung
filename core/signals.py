from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User

# Signal für neue Mitarbeiter
@receiver(post_save, sender=User)
def nach_neuem_mitarbeiter(sender, instance, created, **kwargs):
    if created:
        # Optional: Logging oder Standardaktionen bei neuem Mitarbeiter
        print(f"Neuer Mitarbeiter angelegt: {instance.username} ({instance.mitarbeiter_id})")
