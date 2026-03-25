from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import secrets
import json
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'замените_на_свой_секретный_ключ_12345'

# Путь к базе данных (будет лежать в папке с приложением)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'games.db')

# --- Инициализация базы данных ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Комнаты
    c.execute('''CREATE TABLE IF NOT EXISTS rooms (
                    room_id TEXT PRIMARY KEY,
                    player1_name TEXT,
                    player2_name TEXT,
                    created_at TEXT,
                    game_states TEXT
                )''')
    # Синхрон: ответы на вопросы
    c.execute('''CREATE TABLE IF NOT EXISTS sync_answers (
                    room_id TEXT,
                    player_name TEXT,
                    answers TEXT,
                    PRIMARY KEY (room_id, player_name)
                )''')
    # Мозаика: завершённые фразы и голоса
    c.execute('''CREATE TABLE IF NOT EXISTS mosaic_answers (
                    room_id TEXT,
                    round INTEGER,
                    player_name TEXT,
                    answer TEXT,
                    voted TEXT,
                    PRIMARY KEY (room_id, round, player_name)
                )''')
    # Детектив: состояние
    c.execute('''CREATE TABLE IF NOT EXISTS detective_state (
                    room_id TEXT PRIMARY KEY,
                    secret TEXT,
                    questions_asked INTEGER,
                    asked TEXT,
                    solved BOOLEAN
                )''')
    # Квест: этап
    c.execute('''CREATE TABLE IF NOT EXISTS quest_state (
                    room_id TEXT PRIMARY KEY,
                    step INTEGER,
                    role1 TEXT,
                    role2 TEXT,
                    keeper_ready BOOLEAN,
                    explorer_answer TEXT
                )''')
    # Викторина: вопросы и ответы
    c.execute('''CREATE TABLE IF NOT EXISTS quiz_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT,
                    creator TEXT,
                    question TEXT,
                    correct_answer TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS quiz_answers (
                    room_id TEXT,
                    player_name TEXT,
                    answers TEXT,
                    PRIMARY KEY (room_id, player_name)
                )''')
    conn.commit()
    conn.close()

# --- Вспомогательные функции ---
def get_room(room_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM rooms WHERE room_id=?", (room_id,))
    room = c.fetchone()
    conn.close()
    return room

def create_room(room_id, player_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    game_states = json.dumps({
        'sync': False,
        'mosaic': False,
        'detective': False,
        'quest': False,
        'quiz': False
    })
    c.execute("INSERT INTO rooms (room_id, player1_name, created_at, game_states) VALUES (?, ?, ?, ?)",
              (room_id, player_name, datetime.now().isoformat(), game_states))
    conn.commit()
    conn.close()

def join_room(room_id, player_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE rooms SET player2_name=? WHERE room_id=?", (player_name, room_id))
    conn.commit()
    conn.close()

def get_game_states(room_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT game_states FROM rooms WHERE room_id=?", (room_id,))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else {}

def set_game_state(room_id, game, value):
    states = get_game_states(room_id)
    states[game] = value
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE rooms SET game_states=? WHERE room_id=?", (json.dumps(states), room_id))
    conn.commit()
    conn.close()

def other_player(room, current_player):
    return room[2] if room[1] == current_player else room[1]

# --- Синхрон: вопросы ---
SYNC_QUESTIONS = [
    "Какое любимое блюдо у пары?",
    "Где они мечтают побывать вместе?",
    "Кто чаще шутит?",
    "Какой фильм смотрели вместе последним?",
    "Какое увлечение объединяет их больше всего?"
]

@app.route('/sync', methods=['GET', 'POST'])
def sync():
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    room = get_room(room_id)
    if not room or not room[2]:
        return redirect(url_for('waiting'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if request.method == 'POST':
        answers = [request.form.get(f'q{i}', '').strip() for i in range(len(SYNC_QUESTIONS))]
        c.execute("REPLACE INTO sync_answers (room_id, player_name, answers) VALUES (?, ?, ?)",
                  (room_id, player, json.dumps(answers)))
        conn.commit()
        c.execute("SELECT player_name FROM sync_answers WHERE room_id=?", (room_id,))
        rows = c.fetchall()
        conn.close()
        if len(rows) == 2:
            return redirect(url_for('sync_result'))
        flash('Ваши ответы сохранены. Ждём ответа партнёра.', 'info')
        return redirect(url_for('lobby'))

    c.execute("SELECT answers FROM sync_answers WHERE room_id=? AND player_name=?", (room_id, player))
    row = c.fetchone()
    conn.close()
    saved_answers = json.loads(row[0]) if row else [''] * len(SYNC_QUESTIONS)
    return render_template('sync.html', questions=SYNC_QUESTIONS, saved_answers=saved_answers)

@app.route('/sync_result')
def sync_result():
    room_id = session.get('room_id')
    if not room_id:
        return redirect(url_for('index'))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT player_name, answers FROM sync_answers WHERE room_id=?", (room_id,))
    rows = c.fetchall()
    conn.close()
    if len(rows) != 2:
        flash('Ожидаем ответов обоих игроков', 'error')
        return redirect(url_for('lobby'))

    answers1 = json.loads(rows[0][1])
    answers2 = json.loads(rows[1][1])
    matches = sum(1 for a1, a2 in zip(answers1, answers2) if a1 and a2 and a1.lower() == a2.lower())
    total = len(SYNC_QUESTIONS)
    set_game_state(room_id, 'sync', True)
    return render_template('sync_result.html', matches=matches, total=total, questions=SYNC_QUESTIONS,
                           answers1=answers1, answers2=answers2, player1=rows[0][0], player2=rows[1][0])

# --- Мозаика: 3 раунда ---
MOSAIC_STARTS = [
    "Когда мы созваниваемся, я всегда...",
    "Наше лучшее совместное воспоминание...",
    "Если бы мы могли отправиться в путешествие прямо сейчас, я бы предложил(а)..."
]

@app.route('/mosaic', methods=['GET', 'POST'])
def mosaic():
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    room = get_room(room_id)
    if not room or not room[2]:
        return redirect(url_for('waiting'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT round FROM mosaic_answers WHERE room_id=?", (room_id,))
    rounds = [r[0] for r in c.fetchall()]
    current_round = max(rounds) if rounds else 0
    if current_round >= len(MOSAIC_STARTS):
        conn.close()
        set_game_state(room_id, 'mosaic', True)
        flash('Мозаика завершена! Вы оба прошли все раунды.', 'success')
        return redirect(url_for('lobby'))

    if request.method == 'POST':
        answer = request.form.get('answer', '').strip()
        if answer:
            c.execute("REPLACE INTO mosaic_answers (room_id, round, player_name, answer, voted) VALUES (?, ?, ?, ?, ?)",
                      (room_id, current_round, player, answer, ''))
            conn.commit()
            c.execute("SELECT player_name FROM mosaic_answers WHERE room_id=? AND round=?", (room_id, current_round))
            rows = c.fetchall()
            if len(rows) == 2:
                conn.close()
                return redirect(url_for('mosaic_vote', round=current_round))
            else:
                conn.close()
                flash('Ответ сохранён. Ждём ответа партнёра.', 'info')
                return redirect(url_for('lobby'))
    # GET: показать форму для текущего раунда
    c.execute("SELECT answer FROM mosaic_answers WHERE room_id=? AND round=? AND player_name=?", (room_id, current_round, player))
    existing = c.fetchone()
    conn.close()
    if existing:
        flash('Вы уже ответили на этот раунд. Ожидайте партнёра.', 'info')
        return redirect(url_for('lobby'))
    start_phrase = MOSAIC_STARTS[current_round]
    return render_template('mosaic.html', start_phrase=start_phrase, round_num=current_round+1)

@app.route('/mosaic_vote/<int:round_num>', methods=['GET', 'POST'])
def mosaic_vote(round_num):
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT player_name, answer FROM mosaic_answers WHERE room_id=? AND round=?", (room_id, round_num))
    answers = {row[0]: row[1] for row in c.fetchall()}
    if len(answers) != 2:
        conn.close()
        flash('Ещё не все ответили', 'error')
        return redirect(url_for('lobby'))
    if request.method == 'POST':
        vote = request.form.get('vote')
        if vote in answers:
            c.execute("UPDATE mosaic_answers SET voted=? WHERE room_id=? AND round=? AND player_name=?",
                      (vote, room_id, round_num, player))
            conn.commit()
            c.execute("SELECT voted FROM mosaic_answers WHERE room_id=? AND round=?", (room_id, round_num))
            votes = [r[0] for r in c.fetchall()]
            if all(votes):
                vote_count = {}
                for v in votes:
                    vote_count[v] = vote_count.get(v, 0) + 1
                winner = max(vote_count, key=vote_count.get)
                conn.close()
                return render_template('mosaic_result.html', round_num=round_num+1,
                                       answers=answers, winner=winner, votes=votes)
            else:
                conn.close()
                flash('Голос принят. Ждём голоса партнёра.', 'info')
                return redirect(url_for('lobby'))
    conn.close()
    return render_template('mosaic_vote.html', round_num=round_num+1, answers=answers)

# --- Детектив ---
DETECTIVE_SECRETS = [
    "первый фильм, который смотрели вместе",
    "место, где познакомились",
    "подарок, который запомнился больше всего"
]

@app.route('/detective', methods=['GET', 'POST'])
def detective():
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    room = get_room(room_id)
    if not room or not room[2]:
        return redirect(url_for('waiting'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT secret, questions_asked, asked, solved FROM detective_state WHERE room_id=?", (room_id,))
    state = c.fetchone()
    if not state:
        if room[1] == player:
            if request.method == 'POST':
                secret = request.form.get('secret', '').strip()
                if secret:
                    c.execute("INSERT INTO detective_state (room_id, secret, questions_asked, asked, solved) VALUES (?, ?, ?, ?, ?)",
                              (room_id, secret, 0, '', 0))
                    conn.commit()
                    conn.close()
                    flash('Секрет загадан. Теперь второй игрок может задавать вопросы.', 'success')
                    return redirect(url_for('lobby'))
            conn.close()
            return render_template('detective_choose.html', secrets=DETECTIVE_SECRETS)
        else:
            conn.close()
            flash('Ожидайте, когда партнёр загадает секрет.', 'info')
            return redirect(url_for('lobby'))
    else:
        secret, questions_asked, asked_str, solved = state
        asked = json.loads(asked_str) if asked_str else []
        if solved:
            conn.close()
            set_game_state(room_id, 'detective', True)
            flash('Детектив уже пройден!', 'success')
            return redirect(url_for('lobby'))
        if room[1] == player and secret:
            if request.method == 'POST':
                pass
            conn.close()
            return render_template('detective_master.html', questions_asked=questions_asked, asked=asked, secret=secret)
        else:
            if request.method == 'POST':
                if 'question' in request.form:
                    question = request.form['question'].strip()
                    if question:
                        asked.append(question)
                        c.execute("UPDATE detective_state SET questions_asked=?, asked=? WHERE room_id=?",
                                  (questions_asked+1, json.dumps(asked), room_id))
                        conn.commit()
                        conn.close()
                        flash('Вопрос задан. Ждите ответа от партнёра (обновите страницу).', 'info')
                        return redirect(url_for('lobby'))
                elif 'guess' in request.form:
                    guess = request.form['guess'].strip()
                    if guess.lower() == secret.lower():
                        c.execute("UPDATE detective_state SET solved=1 WHERE room_id=?", (room_id,))
                        conn.commit()
                        conn.close()
                        set_game_state(room_id, 'detective', True)
                        flash('Поздравляем! Вы угадали секрет!', 'success')
                        return redirect(url_for('lobby'))
                    else:
                        flash('Неправильно! Попробуйте ещё раз.', 'error')
                        conn.close()
                        return redirect(url_for('detective'))
            conn.close()
            return render_template('detective_guesser.html', questions_asked=questions_asked, asked=asked, max_questions=10)

# --- Квест ---
QUEST_STEPS = [
    {
        "keeper_prompt": "Вы видите старую карту. На ней нарисован путь: начни с 'A', затем иди на север, потом на восток. Конечная точка — буква?",
        "explorer_prompt": "Хранитель видит карту. Спросите его, куда идти.",
        "expected_answer": "C"
    },
    {
        "keeper_prompt": "На двери замок. На нём выгравировано число: 27. Рядом надпись: 'Чтобы открыть, раздели на 3 и умножь на 2'. Какое число?",
        "explorer_prompt": "Хранитель видит замок. Спросите, как его открыть.",
        "expected_answer": "18"
    },
    {
        "keeper_prompt": "В сундуке лежит записка: 'Слово из трёх букв, которое объединяет вас'. Напишите его.",
        "explorer_prompt": "Хранитель видит записку. Спросите, что там написано.",
        "expected_answer": "мир"
    }
]

@app.route('/quest', methods=['GET', 'POST'])
def quest():
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    room = get_room(room_id)
    if not room or not room[2]:
        return redirect(url_for('waiting'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT step, role1, role2, keeper_ready, explorer_answer FROM quest_state WHERE room_id=?", (room_id,))
    state = c.fetchone()
    if not state:
        role1 = room[1]
        role2 = room[2]
        c.execute("INSERT INTO quest_state (room_id, step, role1, role2, keeper_ready, explorer_answer) VALUES (?, ?, ?, ?, ?, ?)",
                  (room_id, 0, role1, role2, 0, ''))
        conn.commit()
        state = (0, role1, role2, 0, '')
        conn.close()
    else:
        conn.close()
    step = state[0]
    if step >= len(QUEST_STEPS):
        set_game_state(room_id, 'quest', True)
        flash('Квест пройден!', 'success')
        return redirect(url_for('lobby'))

    keeper = state[1]
    explorer = state[2]
    keeper_ready = state[3]
    explorer_answer = state[4]

    if player == keeper:
        if request.method == 'POST':
            if 'ready' in request.form:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE quest_state SET keeper_ready=1 WHERE room_id=?", (room_id,))
                conn.commit()
                conn.close()
                flash('Вы сообщили ответ. Ждите, пока партнёр введёт его.', 'info')
                return redirect(url_for('lobby'))
        return render_template('quest_keeper.html', prompt=QUEST_STEPS[step]['keeper_prompt'], step=step+1)
    else:
        if request.method == 'POST':
            answer = request.form.get('answer', '').strip()
            if answer:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE quest_state SET explorer_answer=? WHERE room_id=?", (answer, room_id))
                conn.commit()
                if keeper_ready:
                    if answer.lower() == QUEST_STEPS[step]['expected_answer'].lower():
                        new_step = step + 1
                        c.execute("UPDATE quest_state SET step=?, keeper_ready=0, explorer_answer='' WHERE room_id=?", (new_step, room_id))
                        conn.commit()
                        conn.close()
                        flash('Верно! Переходим к следующему этапу.', 'success')
                    else:
                        flash('Неправильно. Попробуйте ещё раз!', 'error')
                        c.execute("UPDATE quest_state SET explorer_answer='' WHERE room_id=?", (room_id,))
                        conn.commit()
                        conn.close()
                    return redirect(url_for('quest'))
                else:
                    conn.close()
                    flash('Ваш ответ сохранён. Ждите, пока партнёр сообщит подсказку.', 'info')
                    return redirect(url_for('lobby'))
        return render_template('quest_explorer.html', prompt=QUEST_STEPS[step]['explorer_prompt'], step=step+1)

# --- Викторина ---
@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    room = get_room(room_id)
    if not room or not room[2]:
        return redirect(url_for('waiting'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM quiz_questions WHERE room_id=?", (room_id,))
    has_questions = c.fetchone() is not None
    conn.close()
    if not has_questions:
        return render_template('quiz_mode.html')
    else:
        return redirect(url_for('quiz_play'))

@app.route('/quiz/create', methods=['GET', 'POST'])
def quiz_create():
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    if request.method == 'POST':
        questions = []
        for key in request.form:
            if key.startswith('question'):
                idx = key.split('_')[1]
                q = request.form[key].strip()
                a = request.form.get(f'answer_{idx}', '').strip()
                if q and a:
                    questions.append((q, a))
        if questions:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            for q, a in questions:
                c.execute("INSERT INTO quiz_questions (room_id, creator, question, correct_answer) VALUES (?, ?, ?, ?)",
                          (room_id, player, q, a))
            conn.commit()
            conn.close()
            flash(f'Добавлено {len(questions)} вопросов!', 'success')
            return redirect(url_for('lobby'))
    return render_template('quiz_create.html')

@app.route('/quiz/play', methods=['GET', 'POST'])
def quiz_play():
    room_id = session.get('room_id')
    player = session.get('player_name')
    if not room_id or not player:
        return redirect(url_for('index'))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, question, correct_answer FROM quiz_questions WHERE room_id=?", (room_id,))
    questions = c.fetchall()
    if not questions:
        conn.close()
        flash('Вопросов пока нет. Создайте их!', 'error')
        return redirect(url_for('quiz'))
    if request.method == 'POST':
        answers = {}
        for qid, _, _ in questions:
            ans = request.form.get(f'answer_{qid}', '').strip()
            answers[str(qid)] = ans
        c.execute("REPLACE INTO quiz_answers (room_id, player_name, answers) VALUES (?, ?, ?)",
                  (room_id, player, json.dumps(answers)))
        conn.commit()
        c.execute("SELECT player_name FROM quiz_answers WHERE room_id=?", (room_id,))
        rows = c.fetchall()
        if len(rows) == 2:
            conn.close()
            return redirect(url_for('quiz_result'))
        else:
            conn.close()
            flash('Ваши ответы сохранены. Ждём ответов партнёра.', 'info')
            return redirect(url_for('lobby'))
    c.execute("SELECT answers FROM quiz_answers WHERE room_id=? AND player_name=?", (room_id, player))
    row = c.fetchone()
    conn.close()
    saved_answers = json.loads(row[0]) if row else {}
    return render_template('quiz_play.html', questions=questions, saved_answers=saved_answers)

@app.route('/quiz_result')
def quiz_result():
    room_id = session.get('room_id')
    if not room_id:
        return redirect(url_for('index'))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT player_name, answers FROM quiz_answers WHERE room_id=?", (room_id,))
    rows = c.fetchall()
    if len(rows) != 2:
        conn.close()
        flash('Ожидаем ответов обоих', 'error')
        return redirect(url_for('lobby'))
    answers1 = json.loads(rows[0][1])
    answers2 = json.loads(rows[1][1])
    c.execute("SELECT id, question, correct_answer FROM quiz_questions WHERE room_id=?", (room_id,))
    questions = c.fetchall()
    conn.close()
    results = []
    for qid, question, correct in questions:
        str_qid = str(qid)
        ans1 = answers1.get(str_qid, '')
        ans2 = answers2.get(str_qid, '')
        correct1 = (ans1.lower() == correct.lower())
        correct2 = (ans2.lower() == correct.lower())
        results.append((question, correct, ans1, correct1, ans2, correct2))
    total_correct1 = sum(r[3] for r in results)
    total_correct2 = sum(r[5] for r in results)
    set_game_state(room_id, 'quiz', True)
    return render_template('quiz_result.html', results=results,
                           player1=rows[0][0], player2=rows[1][0],
                           total1=total_correct1, total2=total_correct2)

# --- Основные маршруты ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        player_name = request.form['player_name']
        room_id = secrets.token_hex(4)
        create_room(room_id, player_name)
        session['room_id'] = room_id
        session['player_name'] = player_name
        return redirect(url_for('waiting'))
    return render_template('create.html')

@app.route('/join', methods=['GET', 'POST'])
def join():
    if request.method == 'POST':
        room_id = request.form['room_id']
        player_name = request.form['player_name']
        room = get_room(room_id)
        if not room:
            flash('Комната не найдена', 'error')
            return redirect(url_for('join'))
        if room[2]:
            flash('Комната уже заполнена', 'error')
            return redirect(url_for('join'))
        join_room(room_id, player_name)
        session['room_id'] = room_id
        session['player_name'] = player_name
        return redirect(url_for('lobby'))
    return render_template('join.html')

@app.route('/waiting')
def waiting():
    room_id = session.get('room_id')
    if not room_id:
        return redirect(url_for('index'))
    room = get_room(room_id)
    if room and room[2]:
        return redirect(url_for('lobby'))
    return render_template('waiting.html', room_id=room_id)

@app.route('/lobby')
def lobby():
    room_id = session.get('room_id')
    if not room_id:
        return redirect(url_for('index'))
    room = get_room(room_id)
    if not room or not room[2]:
        return redirect(url_for('waiting'))
    states = get_game_states(room_id)
    all_completed = all(states.values())
    return render_template('lobby.html', states=states, all_completed=all_completed)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- Запуск (для локального тестирования) ---
if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0')