# Raspberry Pi jako serwer operacyjny dla T3 Code

Stan źródeł: 28 sierpnia 2026.

## Rekomendacja

Wybierz **Raspberry Pi OS Lite 64-bit na Raspberry Pi 5**. Uruchom system z NVMe, podłącz Ethernet, dodaj aktywne chłodzenie i użyj osobnego konta bez uprawnień roota do T3 Code. Raspberry Pi OS jest oficjalnym systemem Raspberry Pi, a wersja Lite jest przeznaczona między innymi do serwerów headless. Obecne wydanie 64-bit bazuje na Debianie 13 Trixie ([dokumentacja systemu](https://www.raspberrypi.com/documentation/computers/os.html), [obrazy systemu](https://www.raspberrypi.com/software/operating-systems/)).

Jeśli Raspberry Pi ma wykonywać dwa ciężkie zadania równolegle, wybierz 16 GB RAM. Dla pracy głównie sekwencyjnej 8 GB wystarczy. To zalecenie wynika z charakteru obciążenia, nie z wymagań T3 Code. Kompilatory, testy, serwery językowe i kilka procesów agentów zużyją więcej pamięci niż sam serwer T3. Raspberry Pi 5 ma tylko cztery rdzenie, więc równoległe kompilacje pozostaną jego głównym ograniczeniem ([specyfikacja Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/)).

Jeśli dopiero kupujesz sprzęt, porównaj koszt kompletnego Pi 5 16 GB, NVMe, obudowy, chłodzenia i zasilacza z małym komputerem x86-64 z 16 lub 32 GB RAM. x86-64 ma mniej problemów z binariami deweloperskimi i obrazami kontenerów. Raspberry Pi ma sens, gdy już je masz, zależy Ci na małym poborze energii albo wiesz, że wszystkie używane codebase'y działają na ARM64.

## Wybór systemu

| System | Ocena | Powód |
| --- | --- | --- |
| Raspberry Pi OS Lite 64-bit | Rekomendowany | Ma najlepszą integrację z firmware, bootloaderem i sprzętem Pi. Wersja Lite nie instaluje pulpitu. Raspberry Pi poleca ten system do większości zastosowań. |
| Ubuntu Server 26.04 LTS | Dobra alternatywa | Pi 4 i Pi 5 mają oficjalne obrazy serwerowe ARM64 i certyfikację dla wybranych modeli. Ubuntu LTS dostaje pięć lat bezpłatnych aktualizacji bezpieczeństwa i utrzymania ([obraz dla Raspberry Pi](https://ubuntu.com/download/raspberry-pi), [macierz wspieranych modeli](https://ubuntu.com/hardware/docs/boards/how-to/ubuntu_supported/raspberry-pi/)). Wybierz go, jeśli administrujesz już serwerami Ubuntu i chcesz zachować ten sam sposób pracy. |
| Debian 13 arm64 | Nie na Pi 5 | Debian ma oficjalny port arm64, ale jego własna dokumentacja podaje, że Pi 5 jest wspierane dopiero w Debianie 14 Forky lub Sid. Gotowe obrazy dla wcześniejszych modeli są obrazami dziennymi ([Debian RaspberryPiImages](https://wiki.debian.org/RaspberryPiImages)). Na Pi 4 Debian jest możliwy, lecz daje tu mniej wygody niż Raspberry Pi OS. |

Ubuntu nie daje T3 Code istotnej przewagi. W tym zastosowaniu Raspberry Pi OS Lite ma najmniej części, które trzeba utrzymywać.

Obecnego `./bootstrap apply` z tego repozytorium nie uruchamiaj na Pi. Publiczny bootstrap obsługuje stacje Hyprland na Omarchy i CachyOS, a serwer headless ma inny katalog pakietów, usług i zabezpieczeń. Jeśli zechcesz objąć Pi tym samym repozytorium, dodaj osobny profil lub platformę serwerową dopiero po zaprojektowaniu jej granicy.

## T3 Code i T3 Connect na ARM64

Na serwerze użyj pakietu CLI `t3`, nie aplikacji Electron ani pakietu AUR. Oficjalna instrukcja uruchamia serwer przez `npx t3@latest`; wymaga Node.js `^22.16`, `^23.11` lub `>=24.10` oraz co najmniej jednego zainstalowanego i zalogowanego CLI dostawcy agenta ([instalacja T3 Code](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md)).

Repozytorium Debiana 13 dostarcza Node.js 20.19, który nie spełnia tego wymagania ([pakiet Debiana](https://packages.debian.org/trixie/arm64/nodejs)). Zainstaluj dokładnie przypięty Node.js 24 LTS przez `mise` albo oficjalne binarium Node.js dla Linux ARM64. Aktualna linia 24 jest wspieranym wydaniem LTS ([harmonogram Node.js](https://nodejs.org/en/about/previous-releases)). Po instalacji sprawdź, czy `node` jest dostępny także w nieinteraktywnej sesji SSH. T3 używa takiej sesji przy zdalnym uruchamianiu i dokumentuje obsługę shimów `mise` ([zdalny dostęp](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md)).

ARM64 wygląda na obsługiwaną ścieżkę serwera, ale projekt nie publikuje formalnej macierzy wsparcia dla Raspberry Pi. Kod T3 ma osobny artefakt `cloudflared` dla `linux-arm64` ([`relayClient.ts`](https://github.com/pingdotgg/t3code/blob/main/packages/shared/src/relayClient.ts)) oraz cel monitora zasobów `aarch64-unknown-linux-gnu` ([`ResourceMonitorBinary.ts`](https://github.com/pingdotgg/t3code/blob/main/apps/server/src/resourceTelemetry/ResourceMonitorBinary.ts)). Mimo to przed przeniesieniem pracy wykonaj test na docelowym Pi. T3 jest młodym projektem, a zależności natywne lub CLI wybranego dostawcy mogą mieć własne ograniczenia ARM64.

Uruchom T3 jako usługę użytkownika:

```sh
npx t3@<sprawdzona-wersja> service install
npx t3@<sprawdzona-wersja> service status
```

Na Linuksie instalator tworzy jednostkę użytkownika systemd i włącza lingering, więc usługa startuje po uruchomieniu maszyny i działa po wylogowaniu ([usługa w tle](https://github.com/pingdotgg/t3code/blob/main/docs/user/background-service.md)). Przypnij wersję, którą sprawdziłeś. Klient i serwer najlepiej działają w tej samej wersji, a aktualizacja serwera przerywa aktywną pracę na czas restartu ([aktualizacje T3 Code](https://github.com/pingdotgg/t3code/blob/main/docs/user/updating.md)).

### Dostęp zdalny

Dla dwóch własnych komputerów użyj Tailscale jako prywatnej sieci. T3 Code sam poleca zaufaną sieć mesh zamiast wystawiania serwera do Internetu. Po uruchomieniu usługi w tle opublikuj działający serwer w tailnecie i wygeneruj dane parowania:

```sh
npx t3@<sprawdzona-wersja> pair --tailscale
```

T3 znajdzie uruchomiony serwer, skonfiguruje trwałe mapowanie Tailscale Serve i poda adres HTTPS oraz jednorazowe dane parowania. Do pilota uruchamianego w terminalu możesz zamiast tego użyć `t3 serve --tailscale-serve` ([zdalny dostęp T3 Code](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md)). Tailscale Serve udostępnia usługę tylko urządzeniom w tailnecie i stosuje reguły dostępu tej sieci ([Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)). Nie używaj Tailscale Funnel i nie przekierowuj portów na routerze.

T3 Connect wybierz, jeśli klient nie może należeć do tailnetu. `t3 connect link` instaluje przypięty `cloudflared`, zapisuje zamiar publikacji i uruchamia tunel przy następnym `t3 serve` lub `t3 start`. Tryb headless używa logowania z kodem, więc nie wymaga przeglądarki na Pi ([wewnętrzna dokumentacja T3 Connect](https://github.com/pingdotgg/t3code/blob/main/docs/internals/t3-connect.md)). Nadal warto mieć Tailscale do administracyjnego SSH.

## Oprogramowanie na hoście

Zainstaluj tylko narzędzia potrzebne hostowi i codebase'om:

| Obszar | Oprogramowanie | Uwagi |
| --- | --- | --- |
| Podstawa | `git`, `openssh-server`, `tmux`, `curl`, `ca-certificates`, `jq`, `ripgrep`, `fd-find`, `rsync` | `tmux` służy do napraw i ręcznych zadań. T3 działa przez systemd, nie w sesji `tmux`. |
| Kompilacja | `build-essential`, `pkg-config`, `python3`, `python3-venv` | Przydają się także wtedy, gdy pakiet npm musi zbudować zależność natywną na ARM64. |
| Runtime | `mise`, dokładnie przypięty Node.js 24 LTS, runtime'y wymagane przez repozytoria | Utrzymuj wersje w plikach projektu. Nie polegaj na inicjalizacji interaktywnej powłoki. |
| T3 | `t3` przez `npx`, wybrane CLI dostawcy agenta | T3 nie zawiera Codex CLI, Claude Code ani innych providerów. Logowanie wykonuje się na serwerze. |
| Sieć | Tailscale, OpenSSH | Tailscale oficjalnie wspiera Raspberry Pi OS ([instalacja na Linuxie](https://tailscale.com/docs/install/linux)). |
| GitHub | `gh` z oficjalnego repozytorium GitHub CLI | T3 wymaga `gh` 2.81.0 lub nowszego. Oficjalne wydania mają pakiety Linux ARM64 ([instalacja](https://github.com/cli/cli/blob/trunk/docs/install_linux.md), [integracja T3](https://github.com/pingdotgg/t3code/blob/main/docs/user/source-control.md)). |
| Kopie zapasowe | `restic` i timer systemd | Repozytorium restic jest szyfrowane hasłem i może znajdować się na zdalnym serwerze lub w usłudze obiektowej ([repozytoria restic](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)). |
| Diagnostyka | `nvme-cli`, `smartmontools`, standardowy journal systemd | Kontroluj stan dysku, wolne miejsce, temperaturę i błędy usługi. |

Nie zakładaj, że każdy provider lub każde narzędzie repozytorium ma build ARM64. Sprawdź je w teście akceptacyjnym.

## GitHub i Bitbucket

### GitHub

Zainstaluj oficjalny `gh`, wykonaj `gh auth login`, a następnie sprawdź uwierzytelnienie w ustawieniach Source Control T3. `gh` obsługuje tworzenie, listowanie, sprawdzanie i przeglądanie pull requestów ([polecenia PR](https://cli.github.com/manual/gh_pr), [`gh pr create`](https://cli.github.com/manual/gh_pr_create)).

Do codziennej pracy używaj osobnego klucza SSH serwera do `git fetch` i `git push`. Ogranicz dostęp klucza i konta do potrzebnych repozytoriów. `gh` przechowuje uwierzytelnienie do API niezależnie od transportu Git.

### Bitbucket

Nie instaluj narzędzia tylko dlatego, że nazywa się "Bitbucket CLI". Oficjalny Atlassian CLI ma obecnie komendy `admin`, `jira` i `rovodev`, ale nie ma grupy komend Bitbucket ([referencja ACLI](https://developer.atlassian.com/cloud/acli/reference/commands/)). Dostępne programy `bb` i `bitbucket-cli` są projektami zewnętrznymi.

T3 Code nie potrzebuje osobnego CLI. Ma wbudowane przepływy Bitbucket PR i korzysta z tokenu. Preferuj token dostępu Bitbucket albo parę adres e-mail i API token przekazane jako `T3CODE_BITBUCKET_ACCESS_TOKEN` lub `T3CODE_BITBUCKET_EMAIL` oraz `T3CODE_BITBUCKET_API_TOKEN` ([integracja Source Control T3](https://github.com/pingdotgg/t3code/blob/main/docs/user/source-control.md)). Przechowuj je w pliku środowiska usługi systemd z prawami `0600`, poza repozytorium.

Użyj zakresów `read:repository:bitbucket`, `write:repository:bitbucket`, `read:pullrequest:bitbucket`, `write:pullrequest:bitbucket` i `read:user:bitbucket` tylko wtedy, gdy potrzebujesz pełnego przepływu clone, push i PR. Atlassian opisuje wymagane zakresy oddzielnie dla repozytoriów i pull requestów ([uprawnienia API tokenów](https://support.atlassian.com/bitbucket-cloud/docs/api-token-permissions/)). Hasła aplikacji nie są już właściwą opcją. Atlassian zastąpił je tokenami API i wyłączył stare hasła w 2026 roku ([wycofanie haseł aplikacji](https://support.atlassian.com/bitbucket-cloud/docs/revoke-an-app-password/)).

Jeśli potrzebujesz automatyzacji poza T3, użyj małego, własnego polecenia opartego na `curl` i `jq`. Oficjalne REST API Bitbucket Cloud potrafi listować i tworzyć pull requesty, a minimalne dane nowego PR to tytuł i gałąź źródłowa ([REST API pull requests](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/)). Taki skrypt jest łatwiejszy do audytu niż przypadkowy zewnętrzny CLI.

## Dysk, zasilanie i kopie zapasowe

Nie używaj karty microSD jako głównego dysku roboczego. Dla Pi 5 wybierz NVMe 512 GB lub 1 TB i M.2 HAT+. Raspberry Pi 5 może uruchamiać system bezpośrednio z NVMe, a oficjalna dokumentacja opisuje ten tryb i kolejność bootowania ([NVMe boot](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#nvme-ssd-boot), [M.2 HAT+](https://www.raspberrypi.com/documentation/accessories/m2-hat-plus.html)). Kartę microSD zostaw jako nośnik ratunkowy.

Użyj oficjalnego zasilacza 27 W lub zasilacza 5 V, 5 A dobrej jakości. Dodaj aktywne chłodzenie. Długie kompilacje powodują throttling niechłodzonego Pi 5, a aktywne chłodzenie utrzymuje wydajność przy stałym obciążeniu ([test chłodzenia Raspberry Pi](https://www.raspberrypi.com/news/heating-and-cooling-raspberry-pi-5/)). Jeśli krótkie zaniki zasilania są częste, dodaj UPS z obsługą bezpiecznego wyłączenia.

Kopia na tym samym NVMe nie jest kopią zapasową. Uruchamiaj codzienny, szyfrowany backup `restic` do innego urządzenia lub storage'u poza Pi. Obejmij nim:

- katalogi repozytoriów wraz z `.git`, bo zdalny Git nie zawiera niezatwierdzonych zmian i niewypchniętych gałęzi;
- trwały stan T3 w `~/.t3`;
- własne jednostki systemd i konfigurację hosta;
- zaszyfrowany plik z sekretami tylko wtedy, gdy świadomie chcesz móc je odtworzyć.

Wyklucz `node_modules`, cache, artefakty buildów i obrazy kontenerów. Raz w miesiącu uruchom `restic check`, okresowo `restic check --read-data`, i wykonaj próbne odtworzenie do pustego katalogu. Restic opisuje różnicę między kontrolą struktury a odczytem całych danych ([kontrola integralności](https://restic.readthedocs.io/en/stable/045_working_with_repos.html#checking-integrity-and-consistency)).

## Zabezpieczenia

- Utwórz osobne konto, na przykład `t3`, które jest właścicielem codebase'ów, sesji providerów i usługi T3. Nie uruchamiaj T3 jako root.
- Nie dodawaj konta `t3` do `sudo`. Zacznij od trybu Supervised. T3 domyślnie uruchamia nowe wątki w trybie Full access, a dokumentacja zaleca Supervised przy pierwszej pracy w kosztownym repozytorium ([tryby uprawnień](https://github.com/pingdotgg/t3code/blob/main/docs/user/permission-modes.md)).
- Dopuść SSH tylko kluczami. Wyłącz logowanie roota i hasłem po potwierdzeniu, że oba komputery łączą się kluczem. Raspberry Pi dokumentuje konfigurację kluczy i ograniczenie użytkowników SSH ([zdalny dostęp](https://www.raspberrypi.com/documentation/computers/remote-access.html)).
- Ogranicz reguły tailnetu do dwóch komputerów i konta administracyjnego. Nie wystawiaj portu SSH ani T3 do publicznego Internetu.
- Ustaw UFW na domyślne odrzucanie połączeń przychodzących. Dopuść ruch administracyjny tylko z interfejsu Tailscale. Skonfiguruj dostęp przed włączeniem zapory, aby nie odciąć własnej sesji ([UFW na Raspberry Pi](https://www.raspberrypi.com/documentation/configuration/web-interface/remote-access.html#use-a-firewall)).
- Traktuj linki i tokeny parowania T3 jak hasła. Po utracie urządzenia unieważnij jego sesję przez `t3 auth` ([uwagi bezpieczeństwa T3](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md#security-notes)).
- Sprawdź po `gh auth login`, gdzie GitHub CLI zapisał token. Gdy na serwerze nie ma systemowego magazynu poświadczeń, `gh` może zapisać go w pliku tekstowym ([logowanie GitHub CLI](https://cli.github.com/manual/gh_auth_login)). Ogranicz prawa do katalogu konfiguracji i uwzględnij ten fakt w modelu zagrożeń oraz backupie.
- Nie łącz prywatnych i służbowych repozytoriów w jednej instancji T3, jeśli ich użytkownicy lub zasady dostępu są różne. Serwer wykonuje procesy providerów, operacje Git i odczyty plików w imieniu sparowanego klienta ([architektura T3](https://github.com/pingdotgg/t3code/blob/main/docs/internals/overview.md)).
- Aktualizuj system regularnie, ale aktualizację T3 wykonuj po zakończeniu aktywnych zadań. Najpierw sprawdź nową wersję, potem przypnij ją na serwerze.
- Używaj osobnego git worktree dla każdego równoległego zadania. T3 rozumie worktree jako izolowany workspace wątku ([słownik T3](https://github.com/pingdotgg/t3code/blob/main/docs/internals/glossary.md)). Dwa agenty pracujące w tym samym katalogu mogą sobie nadpisać pliki i stan gałęzi.

## Docker

Nie konteneryzuj samego T3 Code. Oficjalna usługa systemd zapewnia prostszy dostęp do repozytoriów, PTY, CLI providerów, poświadczeń i narzędzi hosta. Docker dodaj tylko wtedy, gdy konkretne repozytorium wymaga Compose, bazy danych lub innej zależności uruchamianej w kontenerze.

Docker Engine obsługuje Debian arm64, ale obrazy używane przez projekty także muszą publikować wariant `linux/arm64` ([wymagania Dockera dla Debiana](https://docs.docker.com/engine/install/debian/)). Docker ostrzega również, że opublikowane porty kontenerów mogą ominąć reguły UFW. Po instalacji sprawdź łańcuch `DOCKER-USER` i nie publikuj usług na wszystkich interfejsach ([ograniczenia zapory](https://docs.docker.com/engine/install/debian/#firewall-limitations)).

## Test akceptacyjny przed migracją

Przez co najmniej dzień uruchom serwer jako pilot i sprawdź:

1. Pi startuje z NVMe i po zimnym restarcie pojawia się w tailnecie.
2. Nieinteraktywne SSH widzi właściwe `node`, CLI providera, `git` i `gh`.
3. `t3 service status` pokazuje działającą usługę po wylogowaniu i restarcie.
4. Oba komputery parują się niezależnie, a stare dane parowania można unieważnić.
5. T3 klonuje repozytorium GitHub i Bitbucket, tworzy osobny worktree, uruchamia testy, wypycha gałąź i tworzy draft PR.
6. Dwa równoległe zadania nie przekraczają dostępnej pamięci, nie wpadają w swap i nie powodują trwałego throttlingu.
7. Aktualizacja T3 zachowuje projekty i sesje, a klient po restarcie łączy się z tą samą wersją serwera.
8. Backup kończy się powodzeniem, `restic check` nie zgłasza błędów, a testowe odtworzenie zawiera repozytorium i stan T3.

Największe ryzyka to brak formalnej gwarancji T3 dla Raspberry Pi, zależności codebase'ów dostępne tylko na x86-64, ograniczone cztery rdzenie oraz wspólne uprawnienia jednej instancji T3. Test dwóch reprezentatywnych repozytoriów przed zakupem pozostałego sprzętu da lepszą odpowiedź niż sama zgodność systemu z ARM64.
