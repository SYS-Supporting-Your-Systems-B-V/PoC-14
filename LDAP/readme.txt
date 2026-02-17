klaarmaken:
cd python/ldap
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # pas aan

starten:
cd python/ldap
. .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8002

sneltest:
curl -s -X POST http://localhost:8000/hpd/search -H "Content-Type: application/json" -d '{"q":"bob","scope":"person","limit":10}' | jq

Pytest draaien:
pip install -r requirements.txt
pip install pytest
pytest -q

Zorg dat .env alleen leesbaar is voor de applicatie-user (chmod 600 .env als je onder Linux draait).
