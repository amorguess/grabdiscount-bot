# ─────────────────────────────────────────────────────────────
#  GrabDiscount — Makefile dev
#  Usage: make help
# ─────────────────────────────────────────────────────────────

.PHONY: help venv install install-dev lint fmt fmt-check test test-cov run-dashboard run-bot run clean deploy vps-logs vps-status vps-restart backup-vps

PYTHON   ?= python3
VENV     ?= .venv
PIP      := $(VENV)/bin/pip
PY       := $(VENV)/bin/python
RUFF     := $(VENV)/bin/ruff
PYTEST   := $(VENV)/bin/pytest

VPS_HOST ?= root@82.197.70.190
VPS_DIR  ?= /root/grabdiscount

help:  ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ─── Setup ──────────────────────────────────────────────────
venv:  ## Crée l'environnement virtuel .venv
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv  ## Installe les dépendances prod
	$(PIP) install -e .

install-dev: venv  ## Installe les dépendances prod + dev
	$(PIP) install -e ".[dev,monitoring]"

# ─── Qualité code ───────────────────────────────────────────
lint:  ## Lance ruff check
	$(RUFF) check .

fmt:  ## Formatte avec ruff
	$(RUFF) format .
	$(RUFF) check --fix .

fmt-check:  ## Vérifie le formatage sans modifier (CI)
	$(RUFF) format --check .
	$(RUFF) check .

# ─── Tests ──────────────────────────────────────────────────
test:  ## Lance les tests
	$(PYTEST)

test-cov:  ## Lance les tests avec coverage
	$(PYTEST) --cov=. --cov-report=term-missing --cov-report=html

# ─── Run local ──────────────────────────────────────────────
run-dashboard:  ## Lance le dashboard Flask en local
	$(PY) dashboard.py

run-bot:  ## Lance le bot Telegram en local
	$(PY) bot.py

run:  ## Lance dashboard + bot (comme en prod)
	$(PY) start.py

# ─── Déploiement VPS ────────────────────────────────────────
deploy:  ## Git push + pull sur VPS + restart systemd
	git push origin main
	ssh $(VPS_HOST) 'cd $(VPS_DIR) && git pull origin main && systemctl restart grabdiscount'
	@echo "✅ Déployé sur VPS"

vps-logs:  ## Suit les logs VPS en temps réel
	ssh $(VPS_HOST) 'journalctl -u grabdiscount -f'

vps-status:  ## Statut du service sur le VPS
	ssh $(VPS_HOST) 'systemctl status grabdiscount'

vps-restart:  ## Redémarre le service VPS
	ssh $(VPS_HOST) 'systemctl restart grabdiscount'

backup-vps:  ## Force un backup maintenant sur le VPS
	ssh $(VPS_HOST) '/root/grabdiscount/backup.sh'

# ─── Nettoyage ──────────────────────────────────────────────
clean:  ## Supprime les artifacts Python
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov

clean-venv: clean  ## Supprime aussi .venv
	rm -rf $(VENV)
