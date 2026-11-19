import os
import time
import json
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template_string, Response, make_response

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "db-service")
DB_NAME = os.getenv("DB_NAME", "votingdb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASSWORD", "secretpassword")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin123")

def get_db_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

def init_db():
    for _ in range(10):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS polls (
                    id SERIAL PRIMARY KEY,
                    question TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE
                );
                CREATE TABLE IF NOT EXISTS options (
                    id SERIAL PRIMARY KEY,
                    poll_id INTEGER REFERENCES polls(id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    votes INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS voter_logs (
                    poll_id INTEGER REFERENCES polls(id) ON DELETE CASCADE,
                    voter_id TEXT NOT NULL,
                    PRIMARY KEY (poll_id, voter_id)
                );
            ''')
            cur.execute("SELECT COUNT(*) FROM polls;")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO polls (question, is_active) VALUES ('Jaki system operacyjny preferujesz?', TRUE) RETURNING id;")
                poll_id = cur.fetchone()[0]
                cur.execute("INSERT INTO options (poll_id, label, votes) VALUES (%s, 'Linux', 0), (%s, 'Windows', 0), (%s, 'macOS', 0);", (poll_id, poll_id, poll_id))
            conn.commit()
            cur.close()
            conn.close()
            break
        except Exception as e:
            print(f"Oczekiwanie na bazę danych: {e}")
            time.sleep(2)

init_db()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>System Głosowania K8s</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; background: #f4f6f8; }
        .card { background: white; padding: 1.5rem; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 1.5rem; }
        button { background: #2563eb; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; margin: 0.25rem 0; }
        button:hover { background: #1d4ed8; }
        button.danger { background: #dc2626; }
        .bar-container { background: #e5e7eb; border-radius: 4px; height: 24px; width: 100%; margin: 4px 0 12px 0; overflow: hidden; }
        .bar { background: #10b981; height: 100%; transition: width 0.3s ease; text-align: right; padding-right: 8px; color: white; font-size: 14px; line-height: 24px; }
        input { padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 0.5rem; width: 95%; }
        .badge { padding: 2px 8px; border-radius: 12px; font-size: 12px; background: #d1fae5; color: #065f46; }
        .badge.closed { background: #fee2e2; color: #991b1b; }
    </style>
</head>
<body>
    <h1>System Głosowania Online (Live SSE)</h1>
    <div id="polls-container">Ładowanie głosowań...</div>

    <div class="card">
        <h3>Panel Administratora</h3>
        <input type="password" id="admin-token" placeholder="Hasło admina (domyślnie: admin123)" value="admin123">
        <input type="text" id="new-question" placeholder="Treść nowego pytania...">
        <input type="text" id="new-options" placeholder="Opcje oddzielone przecinkiem (np. Tak, Nie, Nie wiem)">
        <button onclick="createPoll()">Utwórz głosowanie</button>
    </div>

    <script>
        function renderPolls(polls) {
            const container = document.getElementById('polls-container');
            container.innerHTML = '';
            polls.forEach(poll => {
                const totalVotes = poll.options.reduce((sum, o) => sum + o.votes, 0);
                let html = `<div class="card">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <h2>${poll.question}</h2>
                        <span class="badge ${poll.is_active ? '' : 'closed'}">${poll.is_active ? 'AKTYWNE' : 'ZAMKNIĘTE'}</span>
                    </div>`;
                
                poll.options.forEach(opt => {
                    const pct = totalVotes > 0 ? Math.round((opt.votes / totalVotes) * 100) : 0;
                    html += `<div>
                        <strong>${opt.label}</strong> (${opt.votes} głosów - ${pct}%)
                        ${poll.is_active ? `<button style="float:right; padding:2px 8px;" onclick="vote(${poll.id}, ${opt.id})">Głosuj</button>` : ''}
                        <div class="bar-container"><div class="bar" style="width: ${pct}%">${pct > 5 ? pct + '%' : ''}</div></div>
                    </div>`;
                });

                html += `<div style="margin-top:1rem; border-top:1px solid #eee; padding-top:0.5rem;">
                    <small>Admin: </small>
                    <button onclick="togglePoll(${poll.id})">${poll.is_active ? 'Zamknij' : 'Otwórz'}</button>
                    <button class="danger" onclick="deletePoll(${poll.id})">Usuń</button>
                </div></div>`;
                container.innerHTML += html;
            });
        }

        // Nasłuchiwanie zmian na żywo przez Server-Sent Events (SSE)
        const evtSource = new EventSource('/stream');
        evtSource.onmessage = function(event) {
            renderPolls(JSON.parse(event.data));
        };

        async function vote(pollId, optionId) {
            const res = await fetch('/api/vote', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({poll_id: pollId, option_id: optionId})
            });
            const data = await res.json();
            if (!res.ok) alert(data.error);
        }

        async function createPoll() {
            const token = document.getElementById('admin-token').value;
            const question = document.getElementById('new-question').value;
            const options = document.getElementById('new-options').value.split(',').map(s => s.trim()).filter(Boolean);
            const res = await fetch('/api/polls', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Admin-Token': token},
                body: JSON.stringify({question, options})
            });
            if (!res.ok) alert('Błąd autoryzacji lub danych');
            else { document.getElementById('new-question').value = ''; document.getElementById('new-options').value = ''; }
        }

        async function togglePoll(pollId) {
            const token = document.getElementById('admin-token').value;
            await fetch(`/api/polls/${pollId}/toggle`, { method: 'POST', headers: {'X-Admin-Token': token} });
        }

        async function deletePoll(pollId) {
            const token = document.getElementById('admin-token').value;
            await fetch(`/api/polls/${pollId}`, { method: 'DELETE', headers: {'X-Admin-Token': token} });
        }
    </script>
</body>
</html>
"""

def fetch_all_polls():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM polls ORDER BY id DESC;")
    polls = cur.fetchall()
    for p in polls:
        cur.execute("SELECT id, label, votes FROM options WHERE poll_id = %s ORDER BY id ASC;", (p['id'],))
        p['options'] = cur.fetchall()
    cur.close()
    conn.close()
    return polls

@app.route('/')
def index():
    resp = make_response(render_template_string(HTML_TEMPLATE))
    if not request.cookies.get('voter_id'):
        resp.set_cookie('voter_id', str(uuid.uuid4()), max_age=60*60*24*30)
    return resp

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/api/polls', methods=['GET'])
def get_polls():
    return jsonify(fetch_all_polls())

@app.route('/api/polls', methods=['POST'])
def create_poll():
    if request.headers.get('X-Admin-Token') != ADMIN_TOKEN:
        return jsonify({"error": "Brak uprawnień"}), 403
    data = request.json
    if not data.get('question') or len(data.get('options', [])) < 2:
        return jsonify({"error": "Wymagane pytanie i min. 2 opcje"}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO polls (question) VALUES (%s) RETURNING id;", (data['question'],))
    poll_id = cur.fetchone()[0]
    for opt in data['options']:
        cur.execute("INSERT INTO options (poll_id, label) VALUES (%s, %s);", (poll_id, opt))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "created"}), 201

@app.route('/api/polls/<int:poll_id>/toggle', methods=['POST'])
def toggle_poll(poll_id):
    if request.headers.get('X-Admin-Token') != ADMIN_TOKEN:
        return jsonify({"error": "Brak uprawnień"}), 403
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE polls SET is_active = NOT is_active WHERE id = %s;", (poll_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "toggled"})

@app.route('/api/polls/<int:poll_id>', methods=['DELETE'])
def delete_poll(poll_id):
    if request.headers.get('X-Admin-Token') != ADMIN_TOKEN:
        return jsonify({"error": "Brak uprawnień"}), 403
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM polls WHERE id = %s;", (poll_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route('/api/vote', methods=['POST'])
def vote():
    voter_id = request.cookies.get('voter_id')
    if not voter_id:
        return jsonify({"error": "Brak identyfikatora sesji (włącz cookies)"}), 400
    data = request.json
    poll_id = data.get('poll_id')
    option_id = data.get('option_id')

    # Celowa pętla obliczeniowa (ułatwia wywołanie autoskalowania HPA podczas testów obciążeniowych)
    _ = sum(i * i for i in range(15000))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT is_active FROM polls WHERE id = %s;", (poll_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({"error": "Głosowanie jest zamknięte"}), 400

        # Blokada wielokrotnego głosowania z tej samej sesji
        cur.execute("INSERT INTO voter_logs (poll_id, voter_id) VALUES (%s, %s);", (poll_id, voter_id))
        cur.execute("UPDATE options SET votes = votes + 1 WHERE id = %s AND poll_id = %s;", (option_id, poll_id))
        conn.commit()
        return jsonify({"status": "voted"})
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Już oddałeś głos w tej ankiecie!"}), 409
    finally:
        cur.close()
        conn.close()

@app.route('/stream')
def stream():
    def event_stream():
        last_data = None
        while True:
            current_data = json.dumps(fetch_all_polls())
            if current_data != last_data:
                yield f"data: {current_data}\n\n"
                last_data = current_data
            time.sleep(1)
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)