from django.db import models
from django.contrib.auth.models import AbstractUser
from datetime import timedelta
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):

    ARBEITSZEITWAHL = [
        ("A", "Vollzeit (38h)"),
        ("B", "Normale Teilzeit (6h/Tag, 5 Tage)"),
        ("C", "Individuell"),
        ("D", "Minijob"),
    ]

    ABTEILUNGEN = [
        ("HR", "Personal"),
        ("IT", "IT-Abteilung"),
        ("FI", "Finanzen"),
        ("SA", "Vertrieb / Sales"),
        ("PR", "Produktion"),
        ("LG", "Logistik"),
    ]


    mitarbeiter_id = models.CharField(max_length=10, unique=True)
    arbeitszeitmodell = models.CharField(max_length=1, choices=ARBEITSZEITWAHL, default="A")
    urlaubstage_jahr = models.IntegerField(default=30)
    wochenstunden = models.FloatField(default=38)
    abteilung = models.CharField(max_length=5, choices=ABTEILUNGEN, default="IT")
    abteilungsleiter = models.BooleanField(default=False)

    # SPEZIELLE TEILZEIT → konfigurierbar (wird bei C benötigt)
    mo_stunden = models.FloatField(default=0)
    di_stunden = models.FloatField(default=0)
    mi_stunden = models.FloatField(default=0)
    do_stunden = models.FloatField(default=0)
    fr_stunden = models.FloatField(default=0)
    sa_stunden = models.FloatField(default=0)
    so_stunden = models.FloatField(default=0)

    USERNAME_FIELD = "mitarbeiter_id"
    REQUIRED_FIELDS = ["username"]

    def berechne_wochenstunden(self):
        """Berechnet Wochenstunden automatisch nach Modell."""
        if self.arbeitszeitmodell == "A":
            return 38  # Vollzeit Mo–Do 9h, Fr 7h

        if self.arbeitszeitmodell == "B":
            return 6 * 5  # 30h/Woche

        if self.arbeitszeitmodell == "D":
            return 10  # Minijob Standard

        if self.arbeitszeitmodell == "C":
            # Summe der Tagesstunden
            return sum([
                self.mo_stunden,
                self.di_stunden,
                self.mi_stunden,
                self.do_stunden,
                self.fr_stunden,
                self.sa_stunden,
                self.so_stunden,
            ])

        return self.wochenstunden

    def save(self, *args, **kwargs):
        # beim Speichern automatisch Wochenstunden setzen
        self.wochenstunden = self.berechne_wochenstunden()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.mitarbeiter_id})"

class Entry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    start = models.DateTimeField(null=True, blank=True)
    ende = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start"]

    def __str__(self):
        return f"{self.user.username} - {self.start}"

    @property
    def ist_offen(self):
        return self.start is not None and self.ende is None
    
    class Meta:
        verbose_name = _("Buchung")
        verbose_name_plural = _("Buchungen")


class Vacation(models.Model):
    STATUS_CHOICES = [
        ("pending", "Wartet auf Genehmigung"),
        ("approved", "Genehmigt"),
        ("rejected", "Abgelehnt"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    startdatum = models.DateField()
    enddatum = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    def tage_liste(self):
        delta = self.enddatum - self.startdatum
        return [self.startdatum + timedelta(days=i) for i in range(delta.days + 1)]

    def __str__(self):
        return f"{self.user.username}: {self.startdatum} - {self.enddatum} ({self.status})"

    class Meta:
        verbose_name = _("Urlaubseintrag")
        verbose_name_plural = _("Urlaubseinträge")


class Sickness(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    startdatum = models.DateField()
    enddatum = models.DateField()

    def tage_liste(self):
        delta = self.enddatum - self.startdatum
        return [self.startdatum + timedelta(days=i) for i in range(delta.days + 1)]

    def __str__(self):
        return f"Krankheit {self.user.username}: {self.startdatum} - {self.enddatum}"

    class Meta:
        verbose_name = _("Krankheit")
        verbose_name_plural = _("Krankheiten")


class Holiday(models.Model):
    jahr = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Leer lassen für einen jährlich wiederkehrenden Feiertag."
    )

    monat = models.PositiveSmallIntegerField()
    tag = models.PositiveSmallIntegerField()

    bezeichnung = models.CharField(max_length=100)

    aktiv = models.BooleanField(default=True)

    class Meta:
        ordering = ["jahr", "monat", "tag"]
        verbose_name = _("Feiertag")
        verbose_name_plural = _("Feiertage")
        constraints = [
            models.UniqueConstraint(
                fields=["jahr", "monat", "tag"],
                name="unique_feiertag_jahr_datum"
            )
        ]

    def __str__(self):
        jahr_text = self.jahr if self.jahr else "jährlich"
        return f"{self.tag:02d}.{self.monat:02d}.{jahr_text} - {self.bezeichnung}"



class Notification(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Benutzer",
    )

    title = models.CharField(
        max_length=255,
        verbose_name="Titel",
    )

    message = models.TextField(
        verbose_name="Nachricht",
    )

    url = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Link",
    )

    is_read = models.BooleanField(
        default=False,
        verbose_name="Gelesen",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Erstellt am",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Benachrichtigung")
        verbose_name_plural = _("Benachrichtigungen")

    def __str__(self):
        return f"{self.user} - {self.title}"

