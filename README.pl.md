# PLUM ecoNET Cloud dla Home Assistant

[English](README.md) · [Przykłady automatyzacji PV](examples/pv/README.md)

Społecznościowa integracja usługi **econetcloud.eu**. Odczytuje parametry rekuperatora i pozwala zmieniać obsługiwane ustawienia użytkownika. Projekt jest niezależny od PLUM i SPIROFLEX.

## Sprawdzona konfiguracja

Rekuperator SPIROFLEX ze sterownikiem **ecoVENT MINI OEM H3.4.0 / S001.34**, moduł internetowy H1.1.0 / S005.04 oraz Home Assistant Core **2026.11.2**. Inne modele nie mają jeszcze potwierdzonego sterowania. Encje sterujące powstają wyłącznie po rozpoznaniu oczekiwanego profilu. Odczyty opcjonalnych, niezamontowanych czujników mogą być niedostępne.

## Funkcje

- Temperatury, przepływy, wilgotność, bieżący stan centrali i bypass.
- Zużycie filtrów oraz liczba dni do ich wymiany.
- Wybór: **Pauza, Bieg 1, Bieg 2, Bieg 3, Boost 1, Boost 2**.
- Tryb **Ręczny / Harmonogram**.
- Osobna temperatura komfortu dla każdego z trzech biegów.
- Przycisk **Zakończ Boost**, działający także przy harmonogramie.

Biegi i Pauza wymagają trybu Ręcznego. Integracja zachowuje harmonogramy zapisane w sterowniku i nie zmienia zewnętrznych sygnałów Boost/Kominek. Każda zmiana wymaga potwierdzenia polecenia i ponownego odczytu nastawy ze sterownika.

## Instalacja przez HACS

1. W HACS / Marketplace otwórz zarządzanie repozytoriami niestandardowymi.
2. Dodaj `https://github.com/juras2500/ha-econet-cloud`, kategoria **Integracja**.
3. Zainstaluj **PLUM ecoNET Cloud** i uruchom ponownie HA.
4. Wybierz **Ustawienia → Urządzenia i usługi → Dodaj integrację → PLUM ecoNET Cloud**.
5. Zaloguj się kontem z **econetcloud.eu** i wybierz instalację.

Repozytorium nie jest częścią domyślnego katalogu HACS. Można też ręcznie skopiować katalog `custom_components/econet_cloud` do katalogu `custom_components` konfiguracji HA, uruchomić HA ponownie i dodać integrację.

To konto ecoNET Cloud — login z econet24.com lub hasło lokalnej bramki ecoNET300 nie są jego zamiennikiem. Połączenie wymaga internetu; nie wymaga własnego brokera MQTT ani otwierania portów routera. Hasło nie jest zapisywane; dane sesji potrzebne do odnowienia połączenia są przechowywane na serwerze HA.

## Panel i automatyzacje PV

[`examples/dashboard.view.yaml`](examples/dashboard.view.yaml) to opcjonalny panel z wbudowanych kart HA. Podmień przykładowe identyfikatory encji na swoje.

W [`examples/pv`](examples/pv/README.md) znajdują się pakiety CWU i CO oparte na nadwyżce PV oraz prognozie na następną godzinę. Mają osobne przełączniki zezwalające na uruchamianie. Wymagają przypisania własnych encji i sprawdzenia progów dla danej instalacji. HACS nie instaluje ich automatycznie.

Oryginalna integracja pompy: [ecoNET300 autorstwa jontofront / pblxptr](https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration). Jej kod nie jest częścią tego projektu.

## Zgłaszanie problemów

Podaj wersję HA, model i wersje sterownika oraz kroki prowadzące do błędu. Przydatna jest diagnostyka integracji, po przejrzeniu jej zawartości. Nie publikuj haseł, tokenów, pełnych kopii HA ani prywatnych konfiguracji. Po niepotwierdzonej zmianie sprawdź faktyczną nastawę przed ponowieniem polecenia.

Licencja MIT: [LICENSE](LICENSE). Opis źródeł i zależności: [NOTICE](NOTICE). Testy: instrukcja w [README](README.md#development).
