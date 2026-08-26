# Aplikacja todo dla Androida i Omarchy

Stan rozeznania: 24 sierpnia 2026. Źródła są wyłącznie oficjalne: dokumentacja producentów, ich repozytoria oraz dokumentacja Omarchy.

## Wniosek

Najlepszym wyborem na start jest **Todoist**. Ma dopracowaną aplikację Android, synchronizację obsługiwaną przez usługę, oficjalne API do odczytu i zamykania zadań oraz webhooki. Dzięki temu widget Omarchy może być mały i przewidywalny: pobiera widok `Today`/`Overdue`, pokazuje liczbę zadań w pasku, a w panelu pozwala oznaczać je jako wykonane. Nie trzeba utrzymywać własnego serwera.

Najlepszą opcją otwartą i self-hosted jest **Vikunja**, ale dopiero wtedy, gdy kontrola nad danymi jest ważniejsza niż jakość aplikacji mobilnej. Oficjalny klient Android nadal jest oznaczony jako beta, a dokumentacja Vikunja mówi wprost, że obsługuje podstawowy zakres funkcji. Sam backend jest natomiast wyjątkowo dobry do integracji: ma REST API v2, zakresowe tokeny API i podpisywane webhooki.

Jeśli masz już serwer Nextcloud, rozsądnym drugim wyborem jest **Nextcloud Tasks + Tasks.org**. Android jest dobry, format jest otwarty, ale widget wymaga klienta CalDAV i obsługi `VTODO`/ETagów. To wyraźnie więcej kodu niż integracja REST z Todoist lub Vikunja.

## Porównanie

Ocena dotyczy tego konkretnego zastosowania, nie ogólnej liczby funkcji aplikacji.

| Rozwiązanie | Android | Interfejs na Linuxie | Odczyt i zamykanie z widgetu | Push/webhook | Koszt utrzymania integracji | Werdykt |
|---|---|---|---|---|---|---|
| Todoist | natywna aplikacja, Android 8+ | web; oficjalny klient wspiera Ubuntu 20.04 | oficjalne REST API i CLI z JSON | tak | niski | **najlepszy start** |
| Vikunja | oficjalna aplikacja beta, podstawowe funkcje | web, pakiety desktop, self-hosting | REST API v2, zakresowe tokeny | tak, podpis HMAC | niski po uruchomieniu serwera | **najlepsze self-hosted** |
| Nextcloud Tasks + Tasks.org | natywne Tasks.org lub DAVx5 + klient zadań | web i klienci CalDAV | możliwe przez CalDAV `VTODO`, lecz bardziej złożone | brak prostego webhooka dla widgetu | średni/wysoki | dobre, jeśli Nextcloud już działa |
| TickTick | oficjalna aplikacja | web, klient Linux | oficjalne Open API pozwala pobrać i ukończyć zadanie | brak udokumentowanych webhooków | niski/średni | dobry produkt, słabsza integracja |
| Super Productivity | oficjalny pakiet Android, wspólna aplikacja webowa | Electron/web | brak stabilnego, publicznego API do własnej bazy zadań | brak API webhooków do tego celu | wysoki | odrzuciłbym dla widgetu |
| Taskwarrior | brak zgodnego, oficjalnego klienta Android | znakomite CLI | idealne lokalnie przez CLI | zależy od mechanizmu synchronizacji | średni/wysoki | Android i sync są słabym ogniwem |
| Tasks.org + dowolny CalDAV | natywna aplikacja open source | zależy od serwera/klienta | CalDAV `VTODO` | zwykle polling | średni | sensowna baza wariantu otwartego |

## Szczegóły

### 1. Todoist

To najkrótsza droga do działającego rozwiązania. Todoist ma natywną aplikację Android 8+ oraz web. Oficjalny klient Linux istnieje, lecz [producent wspiera go tylko na Ubuntu 20.04](https://www.todoist.com/help/articles/system-requirements-for-todoist-Bqx0EW), więc na Archu traktowałbym web jako bezpieczniejszy interfejs. Oficjalne [API Todoist](https://developer.todoist.com/api/v1/) jest bezpłatne dla każdego konta i udostępnia zadania, filtrowanie oraz operację ukończenia zadania. Jest też oficjalne CLI `td` z wyjściem JSON. Uwierzytelnianie własnego skryptu może używać osobistego tokenu API, a aplikacja udostępniana innym użytkownikom powinna użyć OAuth. [Webhooki](https://developer.todoist.com/api/v1/#tag/Webhooks) pozwalają reagować na zmiany bez częstego odpytywania.

Dla prywatnego widgetu najprostszy wariant to token zapisany w systemowym magazynie sekretów, lokalny helper HTTP i odświeżanie co 30–60 sekund. Webhook wymaga publicznie osiągalnego endpointu, więc na jednym komputerze polling jest prostszy i wystarczający. Widget może od razu zamykać zadanie przez API, następnie optymistycznie usunąć je z listy i wykonać odświeżenie potwierdzające.

Ryzyko: jest to zamknięta usługa. Trzeba też sprawdzić, czy funkcje planowania potrzebne użytkownikowi mieszczą się w aktualnym [planie Beginner lub Pro](https://todoist.com/pricing). API działa w planie darmowym. Plan Beginner ogranicza między innymi liczbę projektów i filtrów; Pro kosztuje obecnie 5 USD miesięcznie przy płatności rocznej.

### 2. Vikunja

Vikunja daje największą kontrolę bez utraty wygodnego API. Oficjalna dokumentacja opisuje instalację jako pojedynczy pakiet zawierający backend i frontend oraz wspomina o aplikacji desktopowej i mobilnej. Jednocześnie zaznacza, że [aplikacja mobilna obsługuje obecnie podstawowe funkcje](https://vikunja.io/docs/installing/). [Wydania oficjalnej aplikacji Android](https://github.com/go-vikunja/app/releases) mają status beta.

Od strony widgetu jest bardzo dobrze. [REST API v2](https://vikunja.io/docs/api-v2/) publikuje OpenAPI 3.1, ma `GET /tasks` oraz `PATCH /tasks/{id}`, a token API trafia w nagłówku Bearer. Użytkownik może tworzyć [tokeny z ograniczonymi uprawnieniami](https://vikunja.io/help/settings/). [Webhooki użytkownika i projektu](https://vikunja.io/docs/webhooks/) obsługują zdarzenia zadań i podpis HMAC-SHA256.

To dobry wybór, jeśli chcesz hostować usługę i akceptujesz mniej dojrzałego klienta Android. Można też połączyć Vikunja przez CalDAV z Tasks.org, ponieważ [Tasks.org wymienia Vikunja jako zgodny serwer](https://tasks.org/docs/sync_caldav/), ale wtedy część danych może nie odwzorować się idealnie między modelem Vikunja i `VTODO`.

### 3. Nextcloud Tasks + Tasks.org

[Nextcloud Tasks](https://github.com/nextcloud/tasks) jest aplikacją webową i serwerem zadań opartym na CalDAV. Oficjalny README wymienia Android przez DAVx5, Tasks.org, OpenTasks i jtx Board, a Linux przez vdirsyncer, Planify, Kalendar oraz Thunderbird. [Tasks.org](https://tasks.org/docs/sync/) synchronizuje bezpośrednio z CalDAV i zachowuje między innymi tytuł, terminy, ukończenie, podzadania, opis, priorytet, tagi, cykliczność i przypomnienia.

Widget musi wykonywać zapytania CalDAV `REPORT`, parsować iCalendar `VTODO`, a przy ukończeniu zapisać zmieniony obiekt z zachowaniem ETagu. Nextcloud Tasks ostrzega, że ETagi są potrzebne do wykrywania konfliktów. Nextcloud używa endpointu `/remote.php/dav`; przy 2FA lub zewnętrznym logowaniu skrypt powinien dostać [osobne hasło aplikacji](https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/basic.html).

Ten wariant ma sens, gdy Nextcloud już jest częścią infrastruktury. Stawianie całego Nextcloud tylko dla tego widgetu byłoby przerostem formy.

### 4. TickTick

TickTick ma oficjalnego klienta Android i Linux oraz web. [Open API](https://developer.ticktick.com/docs#/openapi) używa OAuth 2.0, a prywatny widget może skorzystać z osobistego tokenu. Udostępnia zakresy `tasks:read` i `tasks:write`, pobieranie niewykonanych zadań, dane projektu wraz z zadaniami oraz endpoint oznaczający zadanie jako ukończone. Istnieje też [oficjalne CLI](https://help.ticktick.com/articles/7465251130025443328). To wystarcza do panelu w Omarchy.

Problemem jest węższa integracja niż w Todoist. Oficjalna dokumentacja Open API nie opisuje webhooków, więc widget musi odpytywać serwer. Endpoint niewykonanych zadań obejmuje maksymalnie 14 dni, a API jest częściowo zorientowane na projekty. Zbudowanie przekrojowego widoku „dzisiaj” wymaga więc więcej logiki po stronie klienta. Produkt jest dobry, szczególnie jeśli liczą się kalendarz, nawyki i Pomodoro, ale dla tego rozszerzenia Todoist ma czystszy kontrakt. Plan darmowy ogranicza liczbę list i zadań, a [Premium kosztuje obecnie 49,99 USD rocznie](https://ticktick.com/upgrade).

### 5. Super Productivity

Super Productivity ma bieżące [wydania Android i Linux](https://github.com/super-productivity/super-productivity/releases) oraz synchronizację przez SuperSync, Dropbox, Nextcloud, WebDAV lub plik lokalny. [Dokumentacja synchronizacji](https://github.com/super-productivity/super-productivity/blob/master/docs/wiki/1.02-Configure-Data-Synchronization.md) opisuje te mechanizmy jako synchronizację stanu aplikacji.

Nie ma natomiast wspieranego publicznego API do odczytu i modyfikacji własnych zadań z osobnego widgetu. Czytanie wewnętrznej bazy aplikacji albo jej pliku synchronizacji związałoby plugin z formatem implementacyjnym, który może się zmienić. To zły fundament dla prostego panelu systemowego.

### 6. Taskwarrior i Tasks.org

Taskwarrior byłby najlepszym backendem po stronie Linuxa. CLI zwraca JSON i pozwala natychmiast ukończyć zadanie. Kłopot zaczyna się na Androidzie. [Tasks.org nie wymienia Taskwarrior jako obsługiwanego mechanizmu synchronizacji](https://tasks.org/docs/sync/). Taskwarrior 3 ma własny [mechanizm synchronizacji](https://taskwarrior.org/docs/man/task-sync.5/), a [nie współpracuje już z serwerem `taskd` z wersji 2](https://taskwarrior.org/docs/upgrade-3/).

Da się zbudować most Taskwarrior ↔ CalDAV lub własną aplikację Android, ale wtedy najtrudniejszą częścią projektu staje się dwukierunkowa synchronizacja i rozwiązywanie konfliktów. Nie warto zaczynać od tego, skoro Todoist, Vikunja i CalDAV już rozwiązują ten problem.

## Jak powinien wyglądać widget Omarchy

Na tym systemie nie trzeba wracać do starego modułu Waybar. Aktualny pasek jest częścią Omarchy Shell i ma oficjalny system pluginów. [Dokumentacja Omarchy](https://github.com/basecamp/omarchy/blob/quattro/manual/32-shell-plugins.md) definiuje plugin `bar-widget`, katalog użytkownika `~/.config/omarchy/plugins/<plugin-id>/` i manifest wskazujący komponent QML. Wbudowany [widget Tailscale](https://github.com/basecamp/omarchy/blob/quattro/shell/plugins/README.md) jest dokładnie takim pluginem z rozwijanym panelem.

Proponowana budowa:

1. `kuba.tasks` jako user-owned plugin Omarchy, bez zmian w źródłach `~/.local/share/omarchy`.
2. Mały helper CLI, który izoluje API dostawcy od QML. Komendy: `list --json`, `complete <id>`, `open <id>`, `refresh`.
3. Ikona i liczba zadań na pasku. Kliknięcie otwiera panel z zadaniami zaległymi i na dziś.
4. Checkbox lub Enter zamyka zadanie. Osobna akcja otwiera je w aplikacji/webie.
5. Cache ostatniego poprawnego wyniku, timeout sieci i czytelny stan offline. Token nigdy nie trafia do `shell.json` ani repozytorium dotfiles.
6. Polling co 30–60 sekund oraz natychmiastowe odświeżenie po otwarciu panelu. Webhook można dodać później, jeśli będzie realna potrzeba.

Takie rozdzielenie pozwoli wymienić Todoist na Vikunja bez przepisywania interfejsu QML. Zmieni się tylko helper.

## Rekomendowana decyzja

Zacząłbym od **Todoist przez dwa tygodnie**, zanim napiszemy plugin. Najpierw trzeba sprawdzić, czy sposób wprowadzania zadań, przypomnienia i widok „dzisiaj” działają w codziennym użyciu na Androidzie. Jeśli tak, budujemy plugin `kuba.tasks` nad oficjalnym API.

Jeśli po próbie przeszkodą okaże się zamknięta usługa albo abonament, wybrałbym **Vikunja**, nie Taskwarrior. API Vikunja daje prawie ten sam prosty model integracji, a własny serwer zachowuje kontrolę nad danymi. Nextcloud wybrałbym tylko wtedy, gdy serwer Nextcloud już istnieje i ma inne zastosowania.
