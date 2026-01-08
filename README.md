Kurz: HSSChatting - Minimaler LAN-Chat mit FastAPI + WebSockets

Features:
- Öffentlicher Hauptchat für alle verbundenen Nutzer
- Private 1:1‑Chats: klicke einen Nutzer in der Sidebar; private Nachrichten sind nur für Sender und Empfänger sichtbar
- Einstellungen: Dein Nick wird lokal gespeichert; ändere ihn unten links in der Sidebar (Einstellungen)
- Verbesserte UI: Sidebar, Kanäle, visuelle Hervorhebung privater Nachrichten und bessere Lesbarkeit (größere Schrift, Kontrast, Lesbarkeit auf mobilen Bildschirmen)

Installation (Windows):
1. Python venv erstellen:
   python -m venv .venv
   .\.venv\Scripts\activate
2. Abhängigkeiten installieren:
   pip install -r requirements.txt

Start (lokal im LAN erreichbar):
- uvicorn app.main:app --host 0.0.0.0 --port 8000

Firewall (nur wenn nötig):
- PowerShell (als Admin):
  New-NetFirewallRule -DisplayName "FastAPI 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000

Test von anderem Gerät im selben LAN:
- Browser: http://<laptop_ip>:8000/
- WebSocket URL (intern): ws://<laptop_ip>:8000/ws

Hinweise:
- Der Chat speichert nichts persistente, alles ist im Arbeitsspeicher.
- Wenn du möchtest, starte ich den Server jetzt und teste kurz die Verbindung (soll ich?).
