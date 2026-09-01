from dataclasses import dataclass


@dataclass(frozen=True)
class FixtureProbe:
    release: str
    outputs: dict[tuple[str, ...], str]

    def os_release(self): return self.release
    def command_output(self, argv): return self.outputs.get(argv)
    def path_exists(self, path): return False
    def architecture(self): return "x86_64"
    def uid(self): return 1000
    def target_home(self): return "/home/tester"
    def pacman_config_digest(self): return "a" * 64
    def repositories(self): return ("core:Required:Sync", "extra:Required:Sync")
    def capabilities(self): return frozenset({"pacman", "graphical-session"})


def cachy_probe() -> FixtureProbe:
    return FixtureProbe(
        'NAME="CachyOS"\nID=cachyos\n',
        {
            ("Hyprland", "--version"): "Hyprland 0.56.2",
            ("uwsm", "--version"): "uwsm 0.24.0",
            ("noctalia", "--version"): "Noctalia 5.0.0",
        },
    )
