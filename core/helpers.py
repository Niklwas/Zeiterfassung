# Neue Logik für Feiertage

import os
import xml.etree.ElementTree as ET

from datetime import date, timedelta
from django.conf import settings

from .models import Holiday, Vacation, Sickness
from setting.models import HolidaySettings

#def get_admin_holidays
from django.db import models
from django.db.models import Q


def get_xml_holidays(year):
    """
    Liest die jahresspezifischen Feiertage aus XML.
    """

    xml_path = os.path.join(
        settings.BASE_DIR,
        "core",
        "holiday_data",
        f"feiertage_{year}_de.xml"
    )

    if not os.path.exists(xml_path):
        return []

    holidays = []

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except (ET.ParseError, OSError):
        return holidays

    for eintrag in root.findall("feiertag"):

        aktiv = eintrag.findtext("aktiv", "true")

        if aktiv.lower() != "true":
            continue

        try:
            tag = int(eintrag.findtext("tag"))
            monat = int(eintrag.findtext("monat"))
        except (TypeError, ValueError):
            continue

        bezeichnung = eintrag.findtext(
            "bezeichnung",
            ""
        )

        holidays.append({
            "tag": tag,
            "monat": monat,
            "bezeichnung": bezeichnung,
        })

    return holidays


def get_admin_holidays(year):
    """
    Liest die zusätzlich im Django-Admin angelegten Feiertage.

    jahr = bestimmtes Jahr:
        Feiertag gilt nur in diesem Jahr.

    jahr = NULL:
        Feiertag gilt jedes Jahr.
    """

    holidays = []

    feiertage = Holiday.objects.filter(
        aktiv=True
    ).filter(
        Q(jahr=year) |
        Q(jahr__isnull=True)
    )

    for feiertag in feiertage:

        holidays.append({
            "tag": feiertag.tag,
            "monat": feiertag.monat,
            "bezeichnung": feiertag.bezeichnung,
        })

    return holidays

def get_holidays(year):
    """
    Gibt alle Feiertage für das angegebene Jahr zurück.

    Quellen:
    1. Jahresspezifische XML-Datei, sofern aktiviert
    2. Feiertage aus dem Django-Admin
    """

    holidays = {}

    # -----------------------------------------
    # Globale Einstellungen
    # -----------------------------------------

    einstellungen = HolidaySettings.objects.first()

    # Standardmäßig XML aktiv,
    # falls noch keine Einstellung existiert.
    xml_aktiv = (
        einstellungen is None
        or einstellungen.xml_feiertage_aktiv
    )

    # -----------------------------------------
    # XML-Feiertage
    # -----------------------------------------

    if xml_aktiv:

        for feiertag in get_xml_holidays(year):

            try:
                datum = date(
                    year,
                    feiertag["monat"],
                    feiertag["tag"]
                )

                holidays[datum] = feiertag["bezeichnung"]

            except ValueError:
                pass

    # -----------------------------------------
    # Admin-Feiertage
    # -----------------------------------------

    for feiertag in get_admin_holidays(year):

        try:
            datum = date(
                year,
                feiertag["monat"],
                feiertag["tag"]
            )

            holidays[datum] = feiertag["bezeichnung"]

        except ValueError:
            pass

    return holidays

def get_jahresdaten(user, year):
    """
    Zentrale Jahresdaten für views.py Funktionen:

    - jahr_view
    - jahr_pdf
    - jahr_pdf_for_user

    Rückgabe:
        feiertage
        feiertagsnamen
        urlaubstage
        krankheitstage

    Feiertage kommen aus get_holidays(year).
    Wochenenden und Feiertage werden NICHT als Urlaubstage gezählt.
    """

    # -----------------------------------
    # FEIERTAGE
    # -----------------------------------

    feiertagsnamen = get_holidays(year)

    # Nur die Datumswerte
    feiertage = set(feiertagsnamen.keys())

    # -----------------------------------
    # URLAUB
    # -----------------------------------

    urlaube = Vacation.objects.filter(
        user=user,
        startdatum__year__lte=year,
        enddatum__year__gte=year,
        status="approved"
    )

    urlaubstage = set()

    for urlaub in urlaube:

        for tag in urlaub.tage_liste():

            # Nur Tage des gewünschten Jahres
            if tag.year != year:
                continue

            # Wochenende
            if tag.weekday() >= 5:
                continue

            # Feiertag
            if tag in feiertage:
                continue

            urlaubstage.add(tag)

    # -----------------------------------
    # KRANKHEIT
    # -----------------------------------

    krankheiten = Sickness.objects.filter(
        user=user,
        startdatum__year__lte=year,
        enddatum__year__gte=year,
    )

    krankheitstage = set()

    for krankheit in krankheiten:

        current = max(
            krankheit.startdatum,
            date(year, 1, 1)
        )

        end = min(
            krankheit.enddatum,
            date(year, 12, 31)
        )

        while current <= end:

            krankheitstage.add(current)

            current += timedelta(days=1)

    # -----------------------------------
    # RÜCKGABE
    # -----------------------------------

    return (
        feiertage,
        feiertagsnamen,
        urlaubstage,
        krankheitstage
    )

def get_urlaubstage(user, year):
    """
    Liefert die tatsächlich angerechneten Urlaubstage.

    Wochenenden und Feiertage werden NICHT
    als Urlaubstage gezählt.
    """

    feiertagsnamen = get_holidays(year)
    feiertage = set(feiertagsnamen.keys())

    urlaube = Vacation.objects.filter(
        user=user,
        startdatum__year__lte=year,
        enddatum__year__gte=year,
        status="approved"
    )

    urlaubstage = set()

    for urlaub in urlaube:

        for tag in urlaub.tage_liste():

            # Nur das gewünschte Jahr
            if tag.year != year:
                continue

            # Samstag / Sonntag ignorieren
            if tag.weekday() >= 5:
                continue

            # Feiertag ignorieren
            if tag in feiertage:
                continue

            urlaubstage.add(tag)

    return urlaubstage