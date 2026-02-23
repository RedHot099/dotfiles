.PHONY: capture install diff dry-run bootstrap

capture:
	./scripts/capture.sh

install:
	./scripts/install.sh

dry-run:
	./scripts/install.sh --dry-run

diff:
	./scripts/diff.sh

bootstrap:
	./scripts/bootstrap-omarchy.sh
