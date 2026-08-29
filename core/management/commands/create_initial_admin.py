import os

from django.core.management.base import BaseCommand
from core.models import User


class Command(BaseCommand):
    help = "Erstellt den initialen Admin-Benutzer, falls er noch nicht existiert."

    def handle(self, *args, **options):
        mitarbeiter_id = "001"

        # Prüfen, ob der Admin bereits existiert
        admin = User.objects.filter(
            mitarbeiter_id=mitarbeiter_id
        ).first()

        if admin:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Admin mit Mitarbeiter-ID '{mitarbeiter_id}' existiert bereits."
                )
            )
            return

        # Passwort aus der Umgebungsvariable lesen
        password = os.getenv("DJANGO_ADMIN_PASSWORD")

        if not password:
            raise RuntimeError(
                "DJANGO_ADMIN_PASSWORD ist nicht gesetzt."
            )

        # Admin erstellen
        admin = User.objects.create_superuser(
            username="admin",
            mitarbeiter_id=mitarbeiter_id,
            password=password,
            arbeitszeitmodell="A",
            urlaubstage_jahr=33,
            abteilung="IT",
            abteilungsleiter=False,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Admin '{admin.mitarbeiter_id}' wurde erfolgreich erstellt."
            )
        )