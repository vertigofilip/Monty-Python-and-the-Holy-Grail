"""Interface languages for the to-do program.

English texts are the keys; other languages map them to translations.
To add a language: add it to LANGUAGES and add its dictionary to _TRANSLATIONS.
"""

from __future__ import annotations

import locale

from . import settings

LANGUAGES: dict[str, str] = {"en": "English", "pl": "Polski"}

_POLISH: dict[str, str] = {
    # main window
    "To-do list": "Lista zadań",
    "New task": "Nowe zadanie",
    "New subtask": "Nowe podzadanie",
    "Edit": "Edytuj",
    "Next stage": "Następny etap",
    "Complete": "Zakończ",
    "Up": "W górę",
    "Down": "W dół",
    "Indent": "Zagnieźdź",
    "Outdent": "Wysuń",
    "Delete": "Usuń",
    "Manage": "Zarządzaj",
    "Users…": "Użytkownicy…",
    "Workflows…": "Przepływy pracy…",
    "Language": "Język",
    "Acting as:": "Działasz jako:",
    "Task": "Zadanie",
    "Stage": "Etap",
    "Priority": "Priorytet",
    "Assignee": "Przypisane do",
    "Tags": "Etykiety",
    "Progress": "Postęp",
    "Repeat": "Powtarzanie",
    "When": "Kiedy",
    "Who": "Kto",
    "Change": "Zmiana",
    "Field": "Pole",
    "Old value": "Stara wartość",
    "New value": "Nowa wartość",
    "system": "system",
    "Select a task first.": "Najpierw wybierz zadanie.",
    'Delete "{name}"?': "Usunąć „{name}”?",
    "This task has subtasks and cannot be deleted.":
        "To zadanie ma podzadania i nie można go usunąć.",
    # login and server mode
    "Account": "Konto",
    "Log in to a server…": "Zaloguj do serwera…",
    "Log out": "Wyloguj",
    "Logged in:": "Zalogowany:",
    "● Connected to {server}": "● Połączono z {server}",
    "● No connection to {server}": "● Brak połączenia z {server}",
    "Refresh": "Odśwież",
    "Where are your tasks?": "Gdzie są Twoje zadania?",
    "On this computer": "Na tym komputerze",
    "Database file": "Plik bazy danych",
    "Database file…": "Plik bazy danych…",
    "Browse…": "Przeglądaj…",
    "Databases": "Bazy danych",
    "All files": "Wszystkie pliki",
    "Cannot open the database {path}.": "Nie można otworzyć bazy danych {path}.",
    "On a server": "Na serwerze",
    "Server address": "Adres serwera",
    "Password": "Hasło",
    "Remember me on this computer": "Zapamiętaj mnie na tym komputerze",
    "Enter email and password.": "Podaj e-mail i hasło.",
    "Enter name and email.": "Podaj nazwę i e-mail.",
    "New password (empty = keep)": "Nowe hasło (puste = bez zmian)",
    "Role": "Rola",
    "Administrator": "Administrator",
    "Admin": "Administrator",
    "User": "Użytkownik",
    "Cannot reach the server at {url}.": "Nie można połączyć się z serwerem {url}.",
    "Login expired. Please log in again.": "Logowanie wygasło. Zaloguj się ponownie.",
    "Server error {code}": "Błąd serwera {code}",
    "Server": "Serwer",
    "Server settings…": "Ustawienia serwera…",
    "Server settings": "Ustawienia serwera",
    "Compress old history automatically": "Automatycznie kompresuj starą historię",
    "Compress history older than (days)": "Kompresuj historię starszą niż (dni)",
    "Runs every night at midnight. Old history entries are merged into "
    "one summary per task; the details are lost.":
        "Działa co noc o północy. Stare wpisy historii są scalane w jedno "
        "podsumowanie na zadanie; szczegóły przepadają.",
    "Days must be a whole number, 0 or more.": "Liczba dni musi być liczbą całkowitą, 0 lub więcej.",
    "Administrators only": "Tylko dla administratorów",
    # phone app
    "Log in": "Zaloguj",
    "Remember me on this phone": "Zapamiętaj mnie na tym telefonie",
    "Enter server address, email and password.": "Podaj adres serwera, e-mail i hasło.",
    "Menu": "Menu",
    "Search": "Szukaj",
    "No tasks to show.": "Brak zadań do pokazania.",
    "Back": "Wstecz",
    "Save": "Zapisz",
    "History": "Historia",
    "Subtask of: {name}": "Podzadanie zadania: {name}",
    "The task is already at the last stage.": "Zadanie jest już na ostatnim etapie.",
    "The task is already done.": "Zadanie jest już zakończone.",
    # messages from the server
    "Wrong email or password": "Nieprawidłowy e-mail lub hasło",
    "Too many failed logins, try again later":
        "Zbyt wiele nieudanych logowań, spróbuj ponownie później",
    "At least one active administrator must remain":
        "Musi pozostać co najmniej jeden aktywny administrator",
    "Conflicts with existing data": "Konflikt z istniejącymi danymi",
    # sorting
    "Sort…": "Sortuj…",
    "Sorting": "Sortowanie",
    "Available fields": "Dostępne pola",
    "Sort by (first = most important)": "Sortuj według (pierwsze = najważniejsze)",
    "Add →": "Dodaj →",
    "← Remove": "← Usuń",
    "Direction": "Kierunek",
    "Reverse direction": "Odwróć kierunek",
    "Clear": "Wyczyść",
    "ascending": "rosnąco",
    "descending": "malejąco",
    "Created at": "Data utworzenia",
    "Manual order (Up / Down) works only when sorting is off.":
        "Ręczna zmiana kolejności (W górę / W dół) działa tylko przy wyłączonym sortowaniu.",
    # filters
    "All": "Wszystkie",
    "(not done)": "(niezakończone)",
    "Filters": "Filtry",
    "Save current sort…": "Zapisz bieżące sortowanie…",
    "Sort presets": "Zapisane sortowania",
    "Sort presets…": "Zapisane sortowania…",
    "Clear sort": "Wyłącz sortowanie",
    "New sort preset": "Nowe zapisane sortowanie",
    "Edit sort preset": "Edytuj zapisane sortowanie",
    "Filter presets": "Zapisane filtry",
    "Filter presets…": "Zapisane filtry…",
    "Save current filters…": "Zapisz bieżące filtry…",
    "Clear filters": "Wyczyść filtry",
    "(no saved presets)": "(brak zapisanych filtrów)",
    "New preset": "Nowy zestaw filtrów",
    "Edit preset": "Edytuj zestaw filtrów",
    "Preset name": "Nazwa zestawu",
    "Task name contains": "Nazwa zadania zawiera",
    "Apply": "Zastosuj",
    "Add…": "Dodaj…",
    "Edit…": "Edytuj…",
    "Select a preset first.": "Najpierw wybierz pozycję z listy.",
    "The preset needs a name.": "Podaj nazwę, pod którą zapisać.",
    'A preset named "{name}" already exists.': "Nazwa „{name}” jest już zajęta.",
    'Delete preset "{name}"?': "Usunąć „{name}”?",
    "Some choices of this preset no longer exist and were set to All: {columns}":
        "Niektóre wybory z tego zestawu już nie istnieją i ustawiono je na „Wszystkie”: {columns}",
    "(overdue)": "(po terminie)",
    "(today)": "(dziś)",
    "(later)": "(później)",
    "Due date": "Termin",
    "Today": "Dziś",
    "No date": "Bez terminu",
    "Calendar": "Kalendarz",
    "Me": "Ja",
    "Without a server": "Bez serwera",
    "Database location…": "Miejsce bazy danych…",
    "Database location": "Miejsce bazy danych",
    "Where the tasks without a server are kept (a file):": "Gdzie są zadania bez serwera (plik):",
    "App storage (private)": "Pamięć aplikacji (prywatna)",
    "App folder on the phone storage": "Folder aplikacji w pamięci telefonu",
    "Documents": "Dokumenty",
    "Use": "Użyj",
    "Places outside the app's own folders, such as Documents, need the “All files access” permission; the app asks for it.":
        "Miejsca poza folderami aplikacji, np. Dokumenty, wymagają uprawnienia „Dostęp do wszystkich plików”; aplikacja o nie poprosi.",
    "Allow “All files access” for To-do in the settings that open now, then come back and tap Use again.":
        "Włącz „Dostęp do wszystkich plików” dla To-do w ustawieniach, które się teraz otworzą, potem wróć i naciśnij jeszcze raz „Użyj”.",
    "{path} does not exist yet. Copy your tasks there, or start with an empty list?":
        "{path} jeszcze nie istnieje. Skopiować tam Twoje zadania czy zacząć od pustej listy?",
    "Copy my tasks": "Skopiuj moje zadania",
    "Start empty": "Zacznij od pustej",
    "No server? Keep the tasks on this phone only.": "Nie masz serwera? Zadania mogą być tylko na tym telefonie.",
    "Tasks on this phone only, without a server.": "Zadania tylko na tym telefonie, bez serwera.",
    "January": "Styczeń", "February": "Luty", "March": "Marzec", "April": "Kwiecień",
    "May": "Maj", "June": "Czerwiec", "July": "Lipiec", "August": "Sierpień",
    "September": "Wrzesień", "October": "Październik", "November": "Listopad",
    "December": "Grudzień",
    "Mon": "Pn", "Tue": "Wt", "Wed": "Śr", "Thu": "Cz", "Fri": "Pt", "Sat": "So", "Sun": "Nd",
    "Location": "Lokalizacja",
    "DueDate": "Termin",
    "YYYY-MM-DD, empty = none": "RRRR-MM-DD, puste = brak",
    "Enter the due date as YYYY-MM-DD, e.g. 2026-10-31.": "Wpisz termin jako RRRR-MM-DD, np. 2026-10-31.",
    "Task reminder": "Przypomnienie o zadaniu",
    "Open the to-do list": "Otwórz listę zadań",
    "Check reminders now": "Sprawdź przypomnienia teraz",
    "Reminders on": "Przypomnienia włączone",
    "Quit": "Zakończ",
    "The program keeps running in the system tray and goes on reminding you.":
        "Program działa dalej w tle i nadal będzie przypominał o zadaniach. "
        "Otworzysz go albo zakończysz ikoną w zasobniku systemowym (obok zegara).",
    "(overdue since {date})": "(po terminie od {date})",
    "…and {n} more": "…i jeszcze {n}",
    "Tasks due: {n}": "Zadania do zrobienia: {n}",
    "Task reminders": "Przypomnienia o zadaniach",
    "Reminders are on": "Przypomnienia są włączone",
    "Reminders": "Przypomnienia",
    "(done)": "(zakończone)",
    "(any)": "(dowolne)",
    # task form
    "Edit task": "Edycja zadania",
    "Name": "Nazwa",
    "Description": "Opis",
    "Repeats": "Powtarzanie",
    "Repeat count (0 = forever)": "Liczba powtórzeń (0 = bez końca)",
    "OK": "OK",
    "Cancel": "Anuluj",
    "(none)": "(brak)",
    "The task needs a name.": "Zadanie musi mieć nazwę.",
    "Repeat count must be a whole number, 0 or more.":
        "Liczba powtórzeń musi być liczbą całkowitą, 0 lub więcej.",
    # priorities
    "Maybe": "Może",
    "Normal": "Normalny",
    "Important": "Ważny",
    # repeat intervals
    "Daily": "Codziennie",
    "Weekly": "Co tydzień",
    "Monthly": "Co miesiąc",
    "Yearly": "Co rok",
    "Every {n} days": "Co {n} dni",
    "Every {n} weeks": "Co {n} tygodnie|Co {n} tygodni",
    "Every {n} months": "Co {n} miesiące|Co {n} miesięcy",
    "Every {n} years": "Co {n} lata|Co {n} lat",
    # urgency
    "Urgency": "Pilność",
    "Low": "Niska",
    "Medium": "Średnia",
    "High": "Wysoka",
    # history: change types
    "Created": "Utworzono",
    "Updated": "Zmieniono",
    "StageChanged": "Zmiana etapu",
    "Completed": "Ukończono",
    "Moved": "Przeniesiono",
    "Deleted": "Usunięto",
    "Compressed": "Skompresowano",
    "{count} changes, {start} – {end}": "zmiany: {count}, {start} – {end}",
    # history: field names
    "StageId": "Etap",
    "AssigneeId": "Przypisane do",
    "RepeatRuleId": "Powtarzanie",
    "RepeatCount": "Liczba powtórzeń",
    "RepeatDone": "Wykonane powtórzenia",
    "ParentId": "Zadanie nadrzędne",
    "Order": "Kolejność",
    # users window
    "Users": "Użytkownicy",
    "Email": "E-mail",
    "Active": "Aktywny",
    "yes": "tak",
    "no": "nie",
    "Add as new": "Dodaj jako nowego",
    "Save changes": "Zapisz zmiany",
    "Deactivate": "Dezaktywuj",
    "Activate": "Aktywuj",
    "Close": "Zamknij",
    "The user needs a name.": "Użytkownik musi mieć nazwę.",
    "Enter a name.": "Wpisz nazwę.",
    "Could not save.": "Nie udało się zapisać.",
    "Could not save. Another user already has this email.":
        "Nie udało się zapisać. Inny użytkownik ma już ten e-mail.",
    "Select a user first.": "Najpierw wybierz użytkownika.",
    "At least one user must stay active.":
        "Co najmniej jeden użytkownik musi pozostać aktywny.",
    # workflows window
    "Workflows": "Przepływy pracy",
    "Workflow": "Przepływ pracy",
    "Final (done)": "Końcowy (gotowe)",
    "Add": "Dodaj",
    "Rename": "Zmień nazwę",
    "Toggle final": "Przełącz końcowy",
    "Name:": "Nazwa:",
    "New workflow": "Nowy przepływ pracy",
    "Rename workflow": "Zmiana nazwy przepływu pracy",
    "New stage": "Nowy etap",
    "Rename stage": "Zmiana nazwy etapu",
    "To do": "Do zrobienia",
    "Done": "Gotowe",
    "Select a workflow first.": "Najpierw wybierz przepływ pracy.",
    "Select a stage first.": "Najpierw wybierz etap.",
    "A workflow with this name already exists.":
        "Przepływ pracy o tej nazwie już istnieje.",
    "At least one workflow must remain.":
        "Musi pozostać co najmniej jeden przepływ pracy.",
    "A workflow needs at least one stage.":
        "Przepływ pracy musi mieć co najmniej jeden etap.",
    '"{name}" is used by {used} task(s) and cannot be deleted.':
        "Nie można usunąć „{name}” – liczba zadań, które go używają: {used}.",
    'Delete workflow "{name}"?': "Usunąć przepływ pracy „{name}”?",
    'Delete stage "{name}"?': "Usunąć etap „{name}”?",
    "Could not delete the workflow.": "Nie udało się usunąć przepływu pracy.",
    "Could not add the stage.": "Nie udało się dodać etapu.",
    "Could not rename the stage.": "Nie udało się zmienić nazwy etapu.",
    "Could not reorder the stages.": "Nie udało się zmienić kolejności etapów.",
    "Could not change the stage.": "Nie udało się zmienić etapu.",
    "Could not delete the stage.": "Nie udało się usunąć etapu.",
    # tags window
    "Tags…": "Etykiety…",
    "Tag": "Etykieta",
    "Tasks": "Zadania",
    "New tag": "Nowa etykieta",
    "Rename tag": "Zmiana nazwy etykiety",
    "Select a tag first.": "Najpierw wybierz etykietę.",
    "A tag with this name already exists.": "Etykieta o tej nazwie już istnieje.",
    'Delete tag "{name}"?': "Usunąć etykietę „{name}”?",
    "Could not delete the tag.": "Nie udało się usunąć etykiety.",
    # Subtask templates
    "Subtask templates": "Szablony podzadań",
    "Subtask templates…": "Szablony podzadań…",
    "From template…": "Z szablonu…",
    "Template": "Szablon",
    "Add as subtasks": "Dodaj jako podzadania",
    'Add subtasks to "{name}" (Ctrl+click chooses several):':
        "Dodaj podzadania do „{name}” (Ctrl+kliknięcie wybiera kilka):",
    "Select a template first.": "Najpierw wybierz szablon.",
    "Select one template to change.": "Wybierz jeden szablon do zmiany.",
    "Delete template(s) {names}?": "Usunąć szablon(y) {names}?",
    "A template with this name already exists.": "Szablon o tej nazwie już istnieje.",
    "Could not delete the template.": "Nie udało się usunąć szablonu.",
    'Add subtasks to "{name}":': "Dodaj podzadania do „{name}”:",
    "New template": "Nowy szablon",
    "No templates yet.": "Nie ma jeszcze szablonów.",
    # A random task
    "Random task": "Losowe zadanie",
    "Another": "Inne",
    "Show in list": "Pokaż na liście",
    "Open": "Otwórz",
    "There are no unfinished tasks without subtasks.":
        "Nie ma niezakończonych zadań bez podzadań.",
}

_TRANSLATIONS: dict[str, dict[str, str]] = {"pl": _POLISH}
_language = "en"


def tr(text: str) -> str:
    """Translate an English interface text into the current language."""
    return _TRANSLATIONS.get(_language, {}).get(text, text)


def tr_n(text: str, n: int) -> str:
    """Translate a text with a count {n}, choosing the plural form.

    A translation may hold two forms separated by "|": the one for 2-4
    (22-24, ...) and the one for everything else, as Polish needs.
    """
    forms = tr(text).split("|")
    few = n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)
    return forms[0 if few or len(forms) == 1 else 1].format(n=n)


def get_language() -> str:
    """Code of the current language."""
    return _language


def set_language(code: str) -> None:
    """Switch the current language; unknown codes fall back to English."""
    global _language
    _language = code if code in LANGUAGES else "en"


def load_language() -> str:
    """The saved language, else the system language if supported, else English."""
    saved = settings.load_setting("language")
    if saved in LANGUAGES:
        return saved
    system = (locale.getlocale()[0] or "")[:2].lower()
    return system if system in LANGUAGES else "en"


def save_language(code: str) -> None:
    """Remember the language for the next start."""
    settings.save_setting("language", code)
