# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from datetime import date, datetime, timedelta
from calendar import monthrange
from .models import Entry, User, Sickness, Holiday
from django.utils.translation import gettext as _

#für einstempeln
from django.utils import timezone

#für monat_view
from django.db.models import Q
from django.utils import timezone


from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO
from django.http import HttpResponse

from .models import Vacation

import requests

#pdf export beliebiger user
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
#from .utils import get_holidays

#urlaub genehmigen
from django.core.mail import send_mail
from django.conf import settings
from .models import Notification
from django.urls import reverse
from setting.email import send_configured_mail

#FÜr Feiertage
from .helpers import get_holidays
from django.db.models import Q
from .helpers import get_jahresdaten
from .helpers import get_urlaubstage




User = get_user_model()

def login_view(request):
    if request.method == "POST":
        mid = request.POST.get("mitarbeiter_id")
        pw = request.POST.get("password")

        user = authenticate(request, mitarbeiter_id=mid, password=pw)
        if user:
            login(request, user)
            return redirect("main")

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")

@login_required
def main_view(request):
    return render(request, "main.html")


@login_required
def einstempeln(request):
    offene_buchung = Entry.objects.filter(
        user=request.user,
        ende__isnull=True,
    ).first()

    # Bereits eingestempelt
    if offene_buchung:
        return redirect("main")

    Entry.objects.create(
        user=request.user,
        start=timezone.now(),
    )

    return redirect("main")

@login_required
def ausstempeln(request):
    buchung = Entry.objects.filter(
        user=request.user,
        ende__isnull=True,
    ).order_by("-start").first()

    if buchung:
        buchung.ende = timezone.now()
        buchung.save()

    return redirect("main")


@login_required
def monat_view(request, year=None, month=None):

    today = timezone.localdate()

    year = int(year or today.year)
    month = int(month or today.month)

    tage_im_monat = monthrange(year, month)[1]

    data = []

    # =========================================================
    # 1. Feiertage
    # =========================================================

    feiertage = get_holidays(year)

    # =========================================================
    # 2. Monatszeitraum
    # =========================================================

    monat_start = date(year, month, 1)
    monat_ende = date(year, month, tage_im_monat)

    # =========================================================
    # 3. Urlaubstage
    # =========================================================

    urlaube = Vacation.objects.filter(
        user=request.user,
        status="approved",
        enddatum__gte=monat_start,
        startdatum__lte=monat_ende,
    )

    urlaubstage = set()

    for u in urlaube:

        start = max(
            u.startdatum,
            monat_start,
        )

        end = min(
            u.enddatum,
            monat_ende,
        )

        current = start

        while current <= end:

            urlaubstage.add(current)

            current += timedelta(days=1)

    # =========================================================
    # 4. Krankheitstage
    # =========================================================

    krankheiten = Sickness.objects.filter(
        user=request.user,
        enddatum__gte=monat_start,
        startdatum__lte=monat_ende,
    )

    krankheitstage = set()

    for k in krankheiten:

        start = max(
            k.startdatum,
            monat_start,
        )

        end = min(
            k.enddatum,
            monat_ende,
        )

        current = start

        while current <= end:

            krankheitstage.add(current)

            current += timedelta(days=1)

    # =========================================================
    # 5. Monatssummen
    # =========================================================

    monats_summe_ist = timedelta()
    monats_summe_soll = timedelta()
    monats_summe_ueber = timedelta()

    # =========================================================
    # 6. Buchungen des Monats
    #
    # Eine Buchung gehört immer zu dem Tag,
    # an dem sie gestartet wurde.
    #
    # Beispiel:
    #
    # 17.08. 22:00 → 18.08. 06:00
    #
    # wird am 17.08. angezeigt.
    # =========================================================

    buchungen = Entry.objects.filter(
        user=request.user,
        start__date__gte=monat_start,
        start__date__lte=monat_ende,
    ).order_by("start")

    # =========================================================
    # 7. Tag-für-Tag
    # =========================================================

    for d in range(1, tage_im_monat + 1):

        datum = date(year, month, d)

        # -----------------------------------------------------
        # Buchungen dieses Tages
        # -----------------------------------------------------

        tages_buchungen = buchungen.filter(
            start__date=datum
        )

        # -----------------------------------------------------
        # Arbeitszeit
        # -----------------------------------------------------

        arbeitszeit = timedelta()

        for buch in tages_buchungen:

            if not buch.start:
                continue

            # Buchung noch offen
            if not buch.ende:

                ende = timezone.now()

                # Nur bis jetzt rechnen
                if ende > buch.start:
                    arbeitszeit += ende - buch.start

            else:

                if buch.ende > buch.start:
                    arbeitszeit += (
                        buch.ende - buch.start
                    )

        # -----------------------------------------------------
        # Erste Buchung / letzter Ausstempel
        # -----------------------------------------------------

        erste_buchung = tages_buchungen.first()

        letzte_buchung = (
            tages_buchungen
            .filter(ende__isnull=False)
            .order_by("-ende")
            .first()
        )

        instempel = (
            erste_buchung.start
            if erste_buchung
            else None
        )

        ausstempel = (
            letzte_buchung.ende
            if letzte_buchung
            else None
        )

        # -----------------------------------------------------
        # Sollzeit
        # -----------------------------------------------------

        weekday = datum.weekday()

        sollzeit = get_sollzeit_for_user(
            request.user,
            weekday,
        )

        # Feiertag / Urlaub / Krankheit
        # → Sollzeit = 0
        if (
            datum in feiertage
            or datum in urlaubstage
            or datum in krankheitstage
        ):
            sollzeit = timedelta(0)

        # -----------------------------------------------------
        # Überstunden
        # -----------------------------------------------------

        ueberstunden = (
            arbeitszeit - sollzeit
        )

        # -----------------------------------------------------
        # Monatssummen
        # -----------------------------------------------------

        monats_summe_ist += arbeitszeit
        monats_summe_soll += sollzeit
        monats_summe_ueber += ueberstunden

        # -----------------------------------------------------
        # Tagesdaten
        # -----------------------------------------------------

        data.append({
            "datum": datum,

            "in": instempel,

            "out": ausstempel,

            "arbeitszeit": format_td(
                arbeitszeit
            ),

            "sollzeit": format_td(
                sollzeit
            ),

            "ueberstunden": format_td(
                ueberstunden
            ),

            "is_weekend": weekday >= 5,

            "is_holiday": (
                datum in feiertage
            ),

            "is_urlaub": (
                datum in urlaubstage
            ),

            "is_krank": (
                datum in krankheitstage
            ),
        })

    # =========================================================
    # 8. Jahressummen
    # =========================================================

    jahres_summe_ist = timedelta()
    jahres_summe_soll = timedelta()
    jahres_summe_ueber = timedelta()

    # =========================================================
    # 9. Urlaubstage für das Jahr
    # =========================================================

    jahres_urlaubstage = set()

    urlaube_jahr = Vacation.objects.filter(
        user=request.user,
        status="approved",
        enddatum__gte=date(year, 1, 1),
        startdatum__lte=date(year, 12, 31),
    )

    for u in urlaube_jahr:

        current = max(
            u.startdatum,
            date(year, 1, 1),
        )

        end = min(
            u.enddatum,
            date(year, 12, 31),
        )

        while current <= end:

            jahres_urlaubstage.add(current)

            current += timedelta(days=1)

    # =========================================================
    # 10. Krankheitstage für das Jahr
    # =========================================================

    jahres_krankheitstage = set()

    krankheiten_jahr = Sickness.objects.filter(
        user=request.user,
        enddatum__gte=date(year, 1, 1),
        startdatum__lte=date(year, 12, 31),
    )

    for k in krankheiten_jahr:

        current = max(
            k.startdatum,
            date(year, 1, 1),
        )

        end = min(
            k.enddatum,
            date(year, 12, 31),
        )

        while current <= end:

            jahres_krankheitstage.add(current)

            current += timedelta(days=1)

    # =========================================================
    # 11. Buchungen des Jahres
    #
    # Auch hier zählt der START der Buchung.
    #
    # Eine Schicht:
    #
    # 17.08. 22:00 → 18.08. 06:00
    #
    # gehört zum 17.08.
    # =========================================================

    jahr_buchungen = Entry.objects.filter(
        user=request.user,
        start__date__gte=date(year, 1, 1),
        start__date__lte=date(year, 12, 31),
    ).order_by("start")

    # =========================================================
    # 12. Jahressummen Tag für Tag
    # =========================================================

    aktuelles_datum = date(year, 1, 1)

    while aktuelles_datum <= date(year, 12, 31):

        tages_buchungen = jahr_buchungen.filter(
            start__date=aktuelles_datum
        )

        arbeitszeit = timedelta()

        for buch in tages_buchungen:

            if not buch.start:
                continue

            if not buch.ende:

                ende = timezone.now()

                if ende > buch.start:
                    arbeitszeit += (
                        ende - buch.start
                    )

            else:

                if buch.ende > buch.start:
                    arbeitszeit += (
                        buch.ende - buch.start
                    )

        # -----------------------------------------------------
        # Sollzeit
        # -----------------------------------------------------

        weekday = aktuelles_datum.weekday()

        soll = get_sollzeit_for_user(
            request.user,
            weekday,
        )

        # Feiertag / Urlaub / Krankheit
        if (
            aktuelles_datum in feiertage
            or aktuelles_datum in jahres_urlaubstage
            or aktuelles_datum in jahres_krankheitstage
        ):
            soll = timedelta(0)

        # -----------------------------------------------------
        # Jahressummen
        # -----------------------------------------------------

        jahres_summe_ist += arbeitszeit

        jahres_summe_soll += soll

        jahres_summe_ueber += (
            arbeitszeit - soll
        )

        aktuelles_datum += timedelta(days=1)

    # =========================================================
    # 13. Navigation
    # =========================================================

    prev_month = (
        month - 1
    ) or 12

    prev_year = (
        year - 1
        if month == 1
        else year
    )

    next_month = (
        month + 1
        if month < 12
        else 1
    )

    next_year = (
        year + 1
        if month == 12
        else year
    )

    # =========================================================
    # 14. Urlaubsauswertung
    # =========================================================

    urlaubstage_jahr = (
        request.user.urlaubstage_jahr
    )

    alle_urlaube = Vacation.objects.filter(
        user=request.user,
        status="approved",
        enddatum__gte=date(year, 1, 1),
        startdatum__lte=date(year, 12, 31),
    )

    urlaub_genommen = 0

    for u in alle_urlaube:

        current = max(
            u.startdatum,
            date(year, 1, 1),
        )

        end = min(
            u.enddatum,
            date(year, 12, 31),
        )

        while current <= end:

            if current.weekday() < 5:
                urlaub_genommen += 1

            current += timedelta(days=1)

    resturlaub = (
        urlaubstage_jahr -
        urlaub_genommen
    )

    # =========================================================
    # 15. Rendern
    # =========================================================

    return render(
        request,
        "monat.html",
        {
            "year": year,
            "month": month,
            "data": data,

            "prev": (
                prev_year,
                prev_month,
            ),

            "next": (
                next_year,
                next_month,
            ),

            "monats_summe_ist": format_td(
                monats_summe_ist
            ),

            "monats_summe_soll": format_td(
                monats_summe_soll
            ),

            "monats_summe_ueber": format_td(
                monats_summe_ueber
            ),

            "jahres_summe_ist": format_td(
                jahres_summe_ist
            ),

            "jahres_summe_soll": format_td(
                jahres_summe_soll
            ),

            "jahres_summe_ueber": format_td(
                jahres_summe_ueber
            ),

            "urlaubstage_jahr": urlaubstage_jahr,

            "urlaub_genommen": urlaub_genommen,

            "resturlaub": resturlaub,
        },
    )

def get_sollzeit_for_user(user, weekday):
    """
    Liefert die Sollzeit für einen Wochentag 0-6 (Mo-So)
    basierend auf dem Arbeitszeitmodell des Mitarbeiters.
    """

    # Vollzeit
    if user.arbeitszeitmodell == "A":
        stunden = {
            0: 9,  # Mo
            1: 9,  # Di
            2: 9,  # Mi
            3: 9,  # Do
            4: 7,  # Fr
            5: 0,
            6: 0,
        }[weekday]
        return timedelta(hours=stunden)

    # Normale Teilzeit
    if user.arbeitszeitmodell == "B":
        stunden = 6 if weekday < 5 else 0
        return timedelta(hours=stunden)

    # Spezielle Teilzeit
    if user.arbeitszeitmodell == "C":
        stunden = [
            user.mo_stunden,
            user.di_stunden,
            user.mi_stunden,
            user.do_stunden,
            user.fr_stunden,
            user.sa_stunden,
            user.so_stunden,
        ][weekday]
        return timedelta(hours=stunden)

    # Falls irgendwas schiefgeht → keine Sollzeit
    return timedelta(0)


#gehört zu def monat_view Punkt4
def format_td(td: timedelta):
    hours = td.seconds // 3600 + td.days * 24
    minutes = (td.seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"



@login_required
def jahr_view(request, year=None):

    year = int(year or date.today().year)

    tage_header = list(range(1, 32))


#    # -----------------------------------
#    # Feiertage, Urlaubstage, Krankheitstage
#    # -----------------------------------

    feiertage, feiertagsnamen, urlaubstage, krankheitstage = get_jahresdaten(
        request.user,
        year
    )

    # -----------------------------------
    # Jahresmatrix
    # -----------------------------------

    matrix = []

    for m in range(1, 13):

        tage = monthrange(year, m)[1]

        row = [
            {
                "monat": m
            }
        ]

        for d in range(1, 32):

            if d <= tage:

                datum = date(
                    year,
                    m,
                    d
                )

                row.append({

                    "tag": d,

                    "wochenende":
                        datum.weekday() >= 5,

                    "urlaub":
                        datum in urlaubstage,

                    "krankheit":
                        datum in krankheitstage,

                    "feiertag":
                        datum in feiertage,

                    "feiertagsname":
                        feiertagsnamen.get(
                            datum,
                            ""
                        ),
                })

            else:

                row.append(None)

        matrix.append(row)


    return render(
        request,
        "jahr.html",
        {
            "year": year,
            "matrix": matrix,
            "tage_header": tage_header,
        }
    )


#Monat2pdf
@login_required
def monat_pdf(request, year=None, month=None):

    today = timezone.localdate()

    year = int(year or today.year)
    month = int(month or today.month)

    # =========================================================
    # PDF Buffer
    # =========================================================

    buffer = BytesIO()

    p = canvas.Canvas(
        buffer,
        pagesize=A4,
    )

    width, height = A4

    # =========================================================
    # Titel
    # =========================================================

    p.setFont(
        "Helvetica-Bold",
        16,
    )

    p.drawString(
        50,
        height - 50,
        _("Monatsübersicht %(month)s/%(year)s – %(user)s") % {
            "month": month,
            "year": year,
            "user": request.user.username,
        },
    )

    # =========================================================
    # Tabellenkopf
    # =========================================================

    y = height - 100

    p.setFont(
        "Helvetica-Bold",
        11,
    )

    p.drawString(40, y, _("Datum"))
    p.drawString(130, y, _("Einstempel"))
    p.drawString(230, y, _("Ausstempel"))
    p.drawString(330, y, _("Arbeitszeit"))

    y -= 20

    p.setFont(
        "Helvetica",
        10,
    )

    # =========================================================
    # Monat
    # =========================================================

    tage = monthrange(
        year,
        month,
    )[1]

    monat_start = date(
        year,
        month,
        1,
    )

    monat_ende = date(
        year,
        month,
        tage,
    )

    # =========================================================
    # Buchungen des Monats
    #
    # Wichtig:
    # Eine Buchung wird anhand ihres STARTDATUMS
    # dem Monat zugeordnet.
    # =========================================================

    buchungen = Entry.objects.filter(
        user=request.user,
        start__date__gte=monat_start,
        start__date__lte=monat_ende,
    ).order_by("start")

    # =========================================================
    # Tag für Tag
    # =========================================================

    for tag in range(
        1,
        tage + 1,
    ):

        datum = date(
            year,
            month,
            tag,
        )

        # -----------------------------------------------------
        # Buchungen dieses Tages
        # -----------------------------------------------------

        tages_buchungen = buchungen.filter(
            start__date=datum
        )

        # -----------------------------------------------------
        # Keine Buchung
        # -----------------------------------------------------

        if not tages_buchungen.exists():

            p.drawString(
                40,
                y,
                datum.strftime(
                    "%d.%m.%Y"
                ),
            )

            p.drawString(130, y, "-")
            p.drawString(230, y, "-")
            p.drawString(330, y, "00:00")

        # -----------------------------------------------------
        # Buchungen vorhanden
        # -----------------------------------------------------

        else:

            erste_buchung = (
                tages_buchungen.first()
            )

            letzte_buchung = (
                tages_buchungen
                .filter(
                    ende__isnull=False
                )
                .order_by("-ende")
                .first()
            )

            # -------------------------------------------------
            # Einstempel
            # -------------------------------------------------

            if (
                erste_buchung
                and erste_buchung.start
            ):

                ein = (
                    erste_buchung.start
                    .astimezone()
                    .strftime("%H:%M")
                )

            else:

                ein = "-"

            # -------------------------------------------------
            # Ausstempel
            # -------------------------------------------------

            if (
                letzte_buchung
                and letzte_buchung.ende
            ):

                aus = (
                    letzte_buchung.ende
                    .astimezone()
                    .strftime("%H:%M")
                )

            else:

                aus = "-"

            # -------------------------------------------------
            # Arbeitszeit
            # -------------------------------------------------

            arbeitszeit = timedelta()

            for buch in tages_buchungen:

                if not buch.start:
                    continue

                # Noch offene Buchung
                if not buch.ende:

                    ende = timezone.now()

                    if ende > buch.start:

                        arbeitszeit += (
                            ende - buch.start
                        )

                # Abgeschlossene Buchung
                else:

                    if buch.ende > buch.start:

                        arbeitszeit += (
                            buch.ende - buch.start
                        )

            # -------------------------------------------------
            # Arbeitszeit formatieren
            # -------------------------------------------------

            gesamt_minuten = int(
                arbeitszeit.total_seconds()
                // 60
            )

            stunden = (
                gesamt_minuten // 60
            )

            minuten = (
                gesamt_minuten % 60
            )

            arbeitszeit_text = (
                f"{stunden:02d}:"
                f"{minuten:02d}"
            )

            # -------------------------------------------------
            # Zeile schreiben
            # -------------------------------------------------

            p.drawString(
                40,
                y,
                datum.strftime(
                    "%d.%m.%Y"
                ),
            )

            p.drawString(130, y, ein)
            p.drawString(230, y, aus)
            p.drawString(330, y, arbeitszeit_text)

        # =====================================================
        # Nächste Zeile
        # =====================================================

        y -= 20

        # =====================================================
        # Neue Seite
        # =====================================================

        if y < 50:

            p.showPage()

            y = height - 50

            # Überschrift auf neuer Seite
            p.setFont(
                "Helvetica-Bold",
                11,
            )

            p.drawString(40, y, _("Datum"))
            p.drawString(130, y, _("Einstempel"))
            p.drawString(230, y, _("Ausstempel"))
            p.drawString(330, y, _("Arbeitszeit"))

            y -= 20

            p.setFont(
                "Helvetica",
                10,
            )

    # =========================================================
    # PDF abschließen
    # =========================================================

    p.showPage()

    p.save()

    buffer.seek(0)

    # =========================================================
    # Download
    # =========================================================

    response = HttpResponse(
        buffer,
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'attachment; '
        f'filename="Monat_{month}_{year}.pdf"'
    )

    return response


@login_required
def urlaub_buchen(request):
    if request.method == "POST":

        # =========================================================
        # 1. URLAUB BUCHEN
        # =========================================================
        if "startdatum" in request.POST and "enddatum" in request.POST:

            start = request.POST.get("startdatum")
            end = request.POST.get("enddatum")

            if not start or not end:
                return render(
                    request,
                    "urlaub_buchen.html",
                    {
                        "error": _(
                            "Bitte Start- und Enddatum angeben."
                        )
                    },
                )

            start = datetime.strptime(start, "%Y-%m-%d").date()
            end = datetime.strptime(end, "%Y-%m-%d").date()

            # Start darf nicht nach Ende liegen
            if start > end:
                return render(
                    request,
                    "urlaub_buchen.html",
                    {
                        "error": _(
                            "Das Startdatum darf nicht "
                            "nach dem Enddatum liegen."
                        )
                    },
                )

            # =====================================================
            # ARBEITSTAGE ERMITTELN
            # Wochenenden + aktive Feiertage werden ausgeschlossen
            # =====================================================

            urlaubstage_neu = []

            aktuelles_datum = start

            while aktuelles_datum <= end:

                # Samstag / Sonntag?
                wochenende = aktuelles_datum.weekday() >= 5

                # Feiertage für das entsprechende Jahr laden
                feiertage = set(get_holidays(aktuelles_datum.year))

                # Ist der Tag ein Feiertag?
                ist_feiertag = aktuelles_datum in feiertage

                # Nur normale Arbeitstage zählen
                if not wochenende and not ist_feiertag:
                    urlaubstage_neu.append(aktuelles_datum)

                aktuelles_datum += timedelta(days=1)

            tage_neu = len(urlaubstage_neu)

            # Falls der komplette Zeitraum nur aus Wochenenden /
            # Feiertagen besteht
            if tage_neu == 0:
                return render(
                    request,
                    "urlaub_buchen.html",
                    {
                        "error": _(
                            "Der ausgewählte Zeitraum enthält "
                            "keine Arbeitstage. Wochenenden und Feiertage "
                            "werden nicht als Urlaubstage gezählt."
                        )
                    }
                )

            # =====================================================
            # BEREITS GENOMMENE URLAUBSTAGE ERMITTELN
            # =====================================================

            urlaube_dieses_jahr = Vacation.objects.filter(
                user=request.user,
                startdatum__year=start.year
            )

            tage_bereits = 0

            for urlaub in urlaube_dieses_jahr:

                aktuelles_datum = urlaub.startdatum

                while aktuelles_datum <= urlaub.enddatum:

                    # Nur Arbeitstage zählen
                    if aktuelles_datum.weekday() < 5:

                        feiertage = set(get_holidays(aktuelles_datum.year))

                        if aktuelles_datum not in feiertage:
                            tage_bereits += 1

                    aktuelles_datum += timedelta(days=1)

            # =====================================================
            # MAXIMALE URLAUBSTAGE PRÜFEN
            # =====================================================

            max_urlaubstage = request.user.urlaubstage_jahr

            if tage_bereits + tage_neu > max_urlaubstage:
                return render(
                    request,
                    "urlaub_buchen.html",
                    {
                        "error": _(
                            "Du kannst maximal %(max)s "
                            "Urlaubstage pro Jahr nehmen. "
                            "Bereits genommen: %(bereits)s, "
                            "neu beantragt: %(neu)s."
                        ) % {
                            "max": max_urlaubstage,
                            "bereits": tage_bereits,
                            "neu": tage_neu,
                        }
                    }
                )

            # =====================================================
            # URLAUB SPEICHERN
            # =====================================================

            Vacation.objects.create(
                user=request.user,
                startdatum=start,
                enddatum=end
            )

            return redirect("urlaub_buchen")

        # =========================================================
        # 2. URLAUB STORNIEREN
        # =========================================================

        delete_id = request.POST.get("delete_id")

        if delete_id:
            try:
                urlaub = Vacation.objects.get(
                    id=delete_id,
                    user=request.user
                )

                urlaub.delete()

                return redirect("urlaub_buchen")

            except Vacation.DoesNotExist:
                return render(
                    request,
                    "urlaub_buchen.html",
                    {
                        "error": _( 
                            "Urlaub nicht gefunden."
                        )
                    }
                )

    # =============================================================
    # GET: URLAUBE DES USERS LADEN
    # =============================================================

    meine_urlaube = Vacation.objects.filter(
        user=request.user
    ).order_by("startdatum")

    return render(
        request,
        "urlaub_buchen.html",
        {
            "meine_urlaube": meine_urlaube
        }
    )


# /Stempelstation /// clockin_station
def clockin_view(request):
    message = ""
    status = None

    if request.method == "POST":

        mitarbeiter_id = request.POST.get("mitarbeiter_id")
        action = request.POST.get("action")

        # ============================================================
        # MITARBEITER SUCHEN
        # ============================================================

        try:
            user = User.objects.get(
                mitarbeiter_id=mitarbeiter_id
            )

        except User.DoesNotExist:
            message = _(
                "Mitarbeiter-ID %(id)s nicht gefunden!"
            ) % {
                "id": mitarbeiter_id,
            }

            return render(
                request,
                "clockin_station.html",
                {
                    "message": message,
                    "status": status,
                }
            )

        # ============================================================
        # AKTUELLE ZEIT
        # ============================================================

        jetzt = timezone.now()

        # ============================================================
        # EINSTEMPELN
        # ============================================================

        if action == "anfang":

            offene_buchung = (
                Entry.objects
                .filter(
                    user=user,
                    ende__isnull=True,
                )
                .order_by("-start")
                .first()
            )

            if offene_buchung:

                lokale_startzeit = timezone.localtime(
                    offene_buchung.start
                )

                message = _(
                    "Bereits eingestempelt um %(time)s."
                ) % {
                    "time": lokale_startzeit.strftime(
                        "%H:%M:%S"
                    )
                }

            else:

                Entry.objects.create(
                    user=user,
                    start=jetzt,
                )

                lokale_zeit = timezone.localtime(
                    jetzt
                )

                message = _(
                    "%(username)s erfolgreich "
                    "eingestempelt um %(time)s."
                ) % {
                    "username": user.username,
                    "time": lokale_zeit.strftime(
                        "%H:%M:%S"
                    ),
                }

        # ============================================================
        # AUSSTEMPELN
        # ============================================================

        elif action == "ende":

            buchung = (
                Entry.objects
                .filter(
                    user=user,
                    ende__isnull=True,
                )
                .order_by("-start")
                .first()
            )

            if not buchung:
                message = _(
                    "%(username)s ist aktuell "
                    "nicht eingestempelt."
                ) % {
                    "username": user.username,
                }

            else:

                buchung.ende = jetzt
                buchung.save(
                    update_fields=["ende"]
                )

                lokale_zeit = timezone.localtime(
                    jetzt
                )

                message = _(
                    "%(username)s erfolgreich "
                    "ausgestempelt um %(time)s."
                ) % {
                    "username": user.username,
                    "time": lokale_zeit.strftime(
                        "%H:%M:%S"
                    ),
                }

        # ============================================================
        # JAHRESSTATUS
        # ============================================================

        elif action == "status":

            # --------------------------------------------------------
            # Aktuelles Jahr
            # --------------------------------------------------------

            year = timezone.localdate().year

            # --------------------------------------------------------
            # Urlaubstage
            # --------------------------------------------------------

            urlaubstage_jahr = user.urlaubstage_jahr

            urlaub_genommen = 0

            alle_urlaube = (
                Vacation.objects
                .filter(
                    user=user,
                    status="approved",
                    startdatum__year=year,
                )
            )

            for urlaub in alle_urlaube:

                current = urlaub.startdatum

                while current <= urlaub.enddatum:

                    # Nur Montag bis Freitag
                    if current.weekday() < 5:
                        urlaub_genommen += 1

                    current += timedelta(days=1)

            resturlaub = (
                urlaubstage_jahr
                - urlaub_genommen
            )

            # --------------------------------------------------------
            # Buchungen des Jahres
            # --------------------------------------------------------

            jahr_buchungen = (
                Entry.objects
                .filter(
                    user=user,
                    start__year=year,
                    ende__isnull=False,
                )
                .order_by("start")
            )

            jahres_summe_ist = timedelta()
            jahres_summe_soll = timedelta()

            # --------------------------------------------------------
            # Feiertage
            # --------------------------------------------------------

            feiertage = get_holidays(year)

            # --------------------------------------------------------
            # Krankheitstage sammeln
            # --------------------------------------------------------

            krankheiten = (
                Sickness.objects
                .filter(
                    user=user,
                    startdatum__year__lte=year,
                    enddatum__year__gte=year,
                )
            )

            krankheitstage = set()

            for krankheit in krankheiten:

                start = max(
                    krankheit.startdatum,
                    date(year, 1, 1)
                )

                end = min(
                    krankheit.enddatum,
                    date(year, 12, 31)
                )

                current = start

                while current <= end:

                    krankheitstage.add(
                        current
                    )

                    current += timedelta(days=1)

            # --------------------------------------------------------
            # Urlaubstage sammeln
            # --------------------------------------------------------

            jahres_urlaubstage = set()

            for urlaub in alle_urlaube:

                start = max(
                    urlaub.startdatum,
                    date(year, 1, 1)
                )

                end = min(
                    urlaub.enddatum,
                    date(year, 12, 31)
                )

                current = start

                while current <= end:

                    jahres_urlaubstage.add(
                        current
                    )

                    current += timedelta(days=1)

            # --------------------------------------------------------
            # Buchungen auswerten
            # --------------------------------------------------------

            for buchung in jahr_buchungen:

                if not buchung.start or not buchung.ende:
                    continue

                # ----------------------------------------------------
                # Tatsächlich gearbeitete Zeit
                # ----------------------------------------------------

                ist = (
                    buchung.ende
                    - buchung.start
                )

                jahres_summe_ist += ist

                # ----------------------------------------------------
                # Lokales Datum der Buchung
                # ----------------------------------------------------

                lokales_startdatum = (
                    timezone.localtime(
                        buchung.start
                    ).date()
                )

                # ----------------------------------------------------
                # Wochentag
                # ----------------------------------------------------

                wd = lokales_startdatum.weekday()

                soll = get_sollzeit_for_user(
                    user,
                    wd
                )

                # ----------------------------------------------------
                # Feiertag / Urlaub / Krankheit
                # ----------------------------------------------------

                if (
                    lokales_startdatum in feiertage
                    or lokales_startdatum in jahres_urlaubstage
                    or lokales_startdatum in krankheitstage
                ):

                    soll = timedelta(0)

                jahres_summe_soll += soll

            # --------------------------------------------------------
            # Überstunden
            # --------------------------------------------------------

            jahres_summe_ueber = (
                jahres_summe_ist
                - jahres_summe_soll
            )

            # --------------------------------------------------------
            # Status-Dict
            # --------------------------------------------------------

            status = {
                "user": user,

                "urlaubstage_jahr": (
                    urlaubstage_jahr
                ),

                "urlaub_genommen": (
                    urlaub_genommen
                ),

                "resturlaub": (
                    resturlaub
                ),

                "jahres_summe_ueber": (
                    format_timedelta(
                        jahres_summe_ueber
                    )
                ),
            }

            message = _(
                "Status für %(username)s berechnet."
            ) % {
                "username": user.username,
            }

        # ============================================================
        # UNBEKANNTE AKTION
        # ============================================================

        else:

            message = _("Ungültige Aktion.")

    # ================================================================
    # TEMPLATE
    # ================================================================

    return render(
        request,
        "clockin_station.html",
        {
            "message": message,
            "status": status,
        }
    )

def format_timedelta(td):
    total_seconds = int(td.total_seconds())
    sign = "-" if total_seconds < 0 else ""
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


@user_passes_test(lambda u: u.is_staff)
def urlaub_genehmigen(request):

    user = request.user

    # -----------------------------
    # 1. Offene Anträge filtern
    # -----------------------------
    offene = Vacation.objects.filter(status="pending")

    # Superuser sieht alle Anträge
    if not user.is_superuser:

        # Abteilungsleiter → nur eigene Abteilung
        if getattr(user, "abteilungsleiter", False):
            offene = offene.filter(user__abteilung=user.abteilung)
        else:
            # normale Mitarbeiter dürfen NICHT hinein
            return redirect("/")  # oder 403-Seite

    # -----------------------------
    # 2. POST = Genehmigung/Ablehnung
    # -----------------------------
    if request.method == "POST":
        uid = request.POST.get("id")
        aktion = request.POST.get("aktion")

        urlaub = get_object_or_404(Vacation, id=uid)

        # Sicherheitscheck: Darf der Benutzer diesen Antrag bearbeiten?
        if not user.is_superuser:
            if getattr(user, "abteilungsleiter", False):
                if urlaub.user.abteilung != user.abteilung:
                    return redirect("urlaub_genehmigen")  # Fremde Abteilung → verboten
            else:
                return redirect("/")  # normale Mitarbeiter


        if aktion == "approve":

            urlaub.status = "approved"
            urlaub.save()


            notification_url = reverse("urlaub_buchen")

            Notification.objects.create(
                user=urlaub.user,
                title=_(
                    "Urlaubsantrag genehmigt"
                ),
                message=_(
                    "Ihr Urlaubsantrag vom %(start)s "
                    "bis %(ende)s wurde genehmigt."
                ) % {
                    "start": urlaub.startdatum,
                    "ende": urlaub.enddatum,
                },
                url=notification_url,
            )

            sende_urlaub_email(urlaub, genehmigt=True)

        elif aktion == "reject":

            urlaub.status = "rejected"
            urlaub.save()


            notification_url = reverse("urlaub_buchen")

            Notification.objects.create(
                user=urlaub.user,
                title=_(
                    "Urlaubsantrag abgelehnt"
                ),
                message=_(
                    "Ihr Urlaubsantrag vom %(start)s "
                    "bis %(ende)s wurde abgelehnt."
                ) % {
                    "start": urlaub.startdatum,
                    "ende": urlaub.enddatum,
                },
                url=notification_url,
            )

            sende_urlaub_email(urlaub, genehmigt=False)

        return redirect("urlaub_genehmigen")


    # -----------------------------
    # 4. Seite rendern
    # -----------------------------
    return render(request, "urlaub_genehmigen.html", {
        "offene": offene
    })


def sende_urlaub_email(urlaub, genehmigt=True):
    mitarbeiter = urlaub.user
    status_text = _("genehmigt") if genehmigt else _("abgelehnt")

    betreff = _(
        "Urlaubsantrag wurde %(status)s"
    ) % {
        "status": status_text,
    }

    text = _(
        "Hallo %(vorname)s,\n\n"
        "Ihr Urlaubsantrag vom %(start)s bis %(ende)s "
        "wurde soeben %(status)s.\n\n"
        "Viele Grüße\n"
        "Ihr Personalteam"
    ) % {
        "vorname": mitarbeiter.first_name,
        "start": urlaub.startdatum,
        "ende": urlaub.enddatum,
        "status": status_text,
    }

    send_configured_mail(
        subject=betreff,
        message=text,
        recipient_list=[mitarbeiter.email],
        fail_silently=False,
    )



#gemeinsame PDF Funktion
def _zeichne_jahres_pdf(
    p,
    user,
    year,
):
    """
    Gemeinsame PDF-Erzeugung für die Jahresübersicht.
    """

    width, height = landscape(A4)

    # -----------------------------------
    # Titel
    # -----------------------------------

    p.setFont(
        "Helvetica-Bold",
        20,
    )

    p.drawString(
        40,
        height - 40,
        _(
            "Jahresübersicht %(year)s – %(user)s"
        ) % {
            "year": year,
            "user": (
                user.get_full_name()
                or user.username
            ),
        },
    )

    # -----------------------------------
    # Jahresdaten
    # -----------------------------------


    (
        feiertage,
        feiertagsnamen,
        urlaubstage,
        krankheitstage,
    ) = get_jahresdaten(
        user,
        year,
    )

    # -----------------------------------
    # Farben
    # -----------------------------------

    COLOR_FEIERTAG = colors.green
    COLOR_URLAUB = colors.lightblue
    COLOR_WEEKEND = colors.yellow
    COLOR_NORMAL = colors.white
    COLOR_KRANK = colors.lightcoral

    # -----------------------------------
    # Tabellenkopf
    # -----------------------------------

    cell_w = 22
    cell_h = 16

    start_x = 50
    start_y = height - 80

    p.setFont(
        "Helvetica-Bold",
        8,
    )

    for d in range(1, 32):
        x = start_x + cell_w * d

        p.drawString(
            x + 6,
            start_y + 5,
            str(d),
        )

    # -----------------------------------
    # Monate rendern
    # -----------------------------------

    p.setFont(
        "Helvetica",
        8,
    )

    monate = [
        _("Jan"),
        _("Feb"),
        _("Mär"),
        _("Apr"),
        _("Mai"),
        _("Jun"),
        _("Jul"),
        _("Aug"),
        _("Sep"),
        _("Okt"),
        _("Nov"),
        _("Dez"),
    ]

    for m in range(1, 13):
        y = start_y - m * cell_h

        p.setFillColor(colors.black)

        p.drawString(
            start_x - 30,
            y + 4,
            monate[m - 1],
        )

        tage_im_monat = monthrange(
            year,
            m,
        )[1]

        for d in range(1, 32):
            if d > tage_im_monat:
                continue

            datum = date(
                year,
                m,
                d,
            )

            # -----------------------------------
            # Farbe bestimmen
            # -----------------------------------

            if datum in feiertage:
                fill = COLOR_FEIERTAG
            elif datum.weekday() >= 5:
                fill = COLOR_WEEKEND
            elif datum in krankheitstage:
                fill = COLOR_KRANK
            elif datum in urlaubstage:
                fill = COLOR_URLAUB
            else:
                fill = COLOR_NORMAL

            # -----------------------------------
            # Zelle zeichnen
            # -----------------------------------

            x = start_x + cell_w * d

            p.setFillColor(fill)

            p.rect(
                x,
                y,
                cell_w,
                cell_h,
                fill=1,
                stroke=1,
            )

            # -----------------------------------
            # Tag
            # -----------------------------------

            p.setFillColor(
                colors.black
            )

            p.drawString(
                x + 7,
                y + 3,
                str(d),
            )

    # -----------------------------------
    # JAHRESZEITEN BERECHNEN
    # -----------------------------------

    jahres_summe_ist = timedelta()
    jahres_summe_soll = timedelta()
    jahres_summe_ueber = timedelta()

    # -----------------------------------
    # Buchungen des Jahres
    #
    # Wichtig:
    # Wir suchen anhand von start.
    #
    # Eine Nachtschicht:
    #
    # 17.08. 22:00
    #       ↓
    # 18.08. 06:00
    #
    # bleibt eine Buchung.
    # -----------------------------------
    jahr_buchungen = (
        Entry.objects
        .filter(
            user=user,
            start__year=year,
        )
        .order_by("start")
    )

    for buch in jahr_buchungen:

        # Offene Buchungen ignorieren
        if not buch.start or not buch.ende:
            continue

        # -----------------------------------
        # Ist-Zeit
        # -----------------------------------
        ist = buch.ende - buch.start

        # Sicherheit gegen fehlerhafte Buchungen
        if ist.total_seconds() < 0:
            continue

        jahres_summe_ist += ist

        # -----------------------------------
        # Tag, an dem die Buchung beginnt
        # -----------------------------------
        datum = buch.start.date()

        # -----------------------------------
        # Sollzeit
        # -----------------------------------
        soll = get_sollzeit_for_user(
            user,
            datum.weekday(),
        )

        # -----------------------------------
        # Feiertag / Urlaub / Krankheit
        # -----------------------------------
        if (
            datum in feiertage
            or datum in urlaubstage
            or datum in krankheitstage
        ):
            soll = timedelta(0)

        jahres_summe_soll += soll

        # -----------------------------------
        # Überstunden
        # -----------------------------------
        jahres_summe_ueber += (
            ist - soll
        )

    # -----------------------------------
    # Zusammenfassung
    # -----------------------------------
    summary_y = 60

    ges_urlaub = len(urlaubstage)
    ges_feiertage = len(feiertage)
    ges_krankheit = len(krankheitstage)

    ges_wochenenden = sum(
        1
        for m in range(1, 13)
        for d in range(
            1,
            monthrange(year, m)[1] + 1,
        )
        if date(
            year,
            m,
            d,
        ).weekday() >= 5
    )

    # -----------------------------------
    # Resturlaub
    # -----------------------------------
    resturlaub = (
        user.urlaubstage_jahr
        - ges_urlaub
    )

    # -----------------------------------
    # Zusammenfassung
    # -----------------------------------
    p.setFont(
        "Helvetica-Bold",
        12,
    )

    p.drawString(
        40,
        summary_y + 50,
        _("Zusammenfassung:"),
    )

    p.setFont(
        "Helvetica",
        11,
    )

    # -----------------------------------
    # IST / SOLL zusätzlich anzeigen
    # -----------------------------------
    p.drawString(
        40,
        summary_y + 30,
        _(
            "- Urlaubstage genommen: %(value)s"
        ) % {
            "value": ges_urlaub,
        },
    )

    p.drawString(
        40,
        summary_y + 10,
        _(
            "- Resturlaub: %(value)s"
        ) % {
            "value": resturlaub,
        },
    )

    p.drawString(
        40,
        summary_y - 10,
        _(
            "- Überstunden gesamt: %(value)s"
        ) % {
            "value": format_timedelta(
                jahres_summe_ueber
            ),
        },
    )

    p.drawString(
        250,
        summary_y + 30,
        _(
            "- Feiertage: %(value)s"
        ) % {
            "value": ges_feiertage,
        },
    )

    p.drawString(
        250,
        summary_y + 10,
        _(
            "- Krankheitstage: %(value)s"
        ) % {
            "value": ges_krankheit,
        },
    )

    p.drawString(
        250,
        summary_y - 10,
        _(
            "- Wochenendtage: %(value)s"
        ) % {
            "value": ges_wochenenden,
        },
    )

    p.drawString(
        40,
        summary_y - 30,
        _(
            "- Arbeitszeit gesamt: %(value)s"
        ) % {
            "value": format_timedelta(
                jahres_summe_ist
            ),
        },
    )

    p.drawString(
        250,
        summary_y - 30,
        _(
            "- Sollzeit gesamt: %(value)s"
        ) % {
            "value": format_timedelta(
                jahres_summe_soll
            ),
        },
    )

    # -----------------------------------
    # Legende
    # -----------------------------------
    p.setFont(
        "Helvetica-Bold",
        12,
    )

    p.drawString(
        500,
        summary_y + 50,
        _("Legende:"),
    )

    p.setFont(
        "Helvetica",
        11,
    )

    legend_items = [
        (
            COLOR_FEIERTAG,
            _("Feiertag"),
            summary_y + 25,
        ),
        (
            COLOR_URLAUB,
            _("Urlaub"),
            summary_y + 10,
        ),
        (
            COLOR_WEEKEND,
            _("Wochenende"),
            summary_y - 5,
        ),
        (
            COLOR_KRANK,
            _("Krankheit"),
            summary_y - 20,
        ),
    ]

    for fill, label, y_pos in legend_items:
        p.setFillColor(fill)

        p.rect(
            500,
            y_pos,
            15,
            10,
            fill=1,
        )

        p.setFillColor(
            colors.black
        )

        p.drawString(
            520,
            y_pos,
            label,
        )



@login_required
def jahr_pdf(request, year=None):

    #Jahresübersicht Export

# ==========================================
# JAHRESÜBERSICHT ALS PDF
# ==========================================
#    
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from calendar import monthrange
    from datetime import date, timedelta
    from io import BytesIO

    year = int(year or date.today().year)

    # -----------------------------------
    # PDF erstellen
    # -----------------------------------

    buffer = BytesIO()

    p = canvas.Canvas(
        buffer,
        pagesize=landscape(A4)
    )

    _zeichne_jahres_pdf(
        p,
        request.user,
        year,
    )

    # -----------------------------------
    # PDF ABSCHLIESSEN
    # -----------------------------------

    p.showPage()
    p.save()

    buffer.seek(0)

    response = HttpResponse(
        buffer,
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        f'attachment; '
        f'filename="Jahresübersicht_{year}.pdf"'
    )

    return response


#Admin-Export
@login_required
def jahr_pdf_for_user(request, user, year=None):

    from datetime import date, timedelta
    from calendar import monthrange
    from io import BytesIO

    from django.http import HttpResponse
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors

    year = int(year or date.today().year)

    # -----------------------------------
    # PDF vorbereiten
    # -----------------------------------

    buffer = BytesIO()

    p = canvas.Canvas(
        buffer,
        pagesize=landscape(A4)
    )

    _zeichne_jahres_pdf(
        p,
        user,
        year,
    )

    # -----------------------------------
    # PDF abschließen
    # -----------------------------------

    p.showPage()

    p.save()

    buffer.seek(0)

    # -----------------------------------
    # Response
    # -----------------------------------

    response = HttpResponse(
        buffer,
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        f'attachment; '
        f'filename="Jahresübersicht_'
        f'{year}_{user.username}.pdf"'
    )

    return response



