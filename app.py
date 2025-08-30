from flask import Flask, render_template, request, redirect, session, url_for, flash
import mysql.connector
from flask_bcrypt import Bcrypt
import csv
import os
from flask import jsonify
import joblib

app = Flask(__name__)
app.secret_key = 'your_secret_key'


# MySQL Connection
def get_mysql_connection():
    return mysql.connector.connect(host='hopper.proxy.rlwy.net',
                                   port=24903,
                                   user='root',
                                   password='IzJJVuFiihaZtqlEYUJgbzPbGXhNnYvL',
                                   database='railway')


bcrypt = Bcrypt(app)

# ─────── Load CSV Data Once ───────

DATA_DIR = 'excelfiles'

# 1) gejala_map: kode_gejala -> nama_gejala
gejala_map = {}
with open(os.path.join(DATA_DIR, 'Kode_Gejala_Laptop.csv'),
          newline='',
          encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        gejala_map[row['kode_gejala']] = row['nama_gejala']

# 2) kerusakan_map: kode_kerusakan -> kerusakan
kerusakan_map = {}
with open(os.path.join(DATA_DIR, 'Kode_Kerusakan_Laptop.csv'),
          newline='',
          encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        kerusakan_map[row['kode_kerusakan']] = row['kerusakan']

# 3) rules_list: raw rules from CSV
rules_list = []
with open(os.path.join(DATA_DIR, 'Rule_Kerusakan_Laptop.csv'),
          newline='',
          encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        # parse the comma‑separated kode_gejala field
        codes = [
            code.strip() for code in row['kode_gejala'].split(',')
            if code.strip()
        ]
        rules_list.append({
            'kode_kerusakan': row['kode_kerusakan'],
            'kode_gejala_list': codes
        })
# ─────── Load repair steps once ───────

# 4) perbaikan_map: kode_perbaikan -> langkah_perbaikan
perbaikan_map = {}
with open(os.path.join(DATA_DIR, 'Kode_perbaikan_laptop.csv'),
          newline='',
          encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        # CSV header may be 'kode_perbaikan' or 'Kode_perbaikan'
        kode_p = row.get('kode_perbaikan') or row.get('Kode_perbaikan')
        langkah = row.get('langkah_perbaikan')
        if kode_p and langkah:
            perbaikan_map[kode_p] = langkah
print(perbaikan_map)
# 5) perbaikan_rules: kode_kerusakan -> [kode_perbaikan,...]
perbaikan_rules = {}
with open(os.path.join(DATA_DIR, 'Rule_perbaikan.csv'),
          newline='',
          encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        kode_k = row.get('kode_kerusakan')
        kode_p = row.get('kode_perbaikan') or row.get('Kode_perbaikan')
        if kode_k and kode_p:
            perbaikan_rules.setdefault(kode_k, []).append(kode_p)
print(perbaikan_rules)


def build_rule_data():
    """Return list of dicts: kode_kerusakan, kerusakan_name, gejala_list (full names)."""
    rd = []
    for rule in rules_list:
        kode = rule['kode_kerusakan']
        kerusakan_name = kerusakan_map.get(kode, kode)
        gejala_names = [
            gejala_map.get(code, code) for code in rule['kode_gejala_list']
        ]
        rd.append({
            'kode_kerusakan': kode,
            'kerusakan_name': kerusakan_name,
            'gejala_list': gejala_names
        })
    return rd


# ─────── Routes ───────


@app.route('/')
def home():
    return redirect(
        url_for('dashboard')) if 'username' in session else redirect(
            url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        pw = request.form['pw']
        name = request.form['name']
        email = request.form['email']
        hashed = bcrypt.generate_password_hash(pw).decode()
        isadmin = int(request.form['isadmin'])
        conn = get_mysql_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO user (username,pw,name,email,isadmin) VALUES (%s,%s,%s,%s,%s)",
                (username, hashed, name, email, isadmin))
            conn.commit()
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Registration failed: {e}', 'danger')
        finally:
            cur.close()
            conn.close()

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        pw = request.form['pw']

        conn = get_mysql_connection()
        cur = conn.cursor()
        cur.execute("SELECT username,pw FROM user WHERE username=%s",
                    (username, ))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and bcrypt.check_password_hash(row[1], pw):
            session['username'] = row[0]
            flash('Login successful.', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'danger')

    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        flash('Please log in first.', 'warning')
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=session['username'])


@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/dictionary')
def dictionary():
    return render_template('dictionary.html', rules=build_rule_data())


@app.route('/diagnosis', methods=['GET', 'POST'])
def diagnose():
    if 'username' not in session:
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))

    result = None
    selected = request.form.getlist(
        'gejala') if request.method == 'POST' else []

    # match rules
    matches = []
    for rule in rules_list:
        if set(rule['kode_gejala_list']).issubset(set(selected)):
            matches.append(rule['kode_kerusakan'])

    if matches:
        # most frequent match
        best = max(set(matches), key=matches.count)
        result = f"{best} - {kerusakan_map.get(best,best)}"
    elif request.method == 'POST':
        result = "No matching diagnosis found."

    return render_template('diagnosis.html',
                           gejala_list=[{
                               'kode_gejala': k,
                               'nama_gejala': v
                           } for k, v in gejala_map.items()],
                           selected_gejala=selected,
                           result=result,
                           rules=build_rule_data())


@app.route('/get_steps/<kode_kerusakan>')
def get_steps(kode_kerusakan):
    codes = perbaikan_rules.get(kode_kerusakan, [])
    steps = [
        perbaikan_map.get(code, f"Step for {code} not found") for code in codes
    ]
    return jsonify(steps=steps)


@app.route('/edit-dataset')
def edit_dataset():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']

    try:
        conn = get_mysql_connection()
        with conn.cursor() as cursor:
            sql = "SELECT isadmin FROM user WHERE username = %s"
            cursor.execute(sql, (username, ))
            result = cursor.fetchone()

            if result is None:
                flash("User not found.")
                return redirect(url_for('dashboard'))

            isadmin = result[0]  # or result['isadmin'] if using DictCursor

            if isadmin != 1:
                flash("You are not admin.")
                return redirect(url_for('dashboard'))

    except Exception as e:
        print("DB Error:", e)
        flash("Internal server error.")
        return redirect(url_for('dashboard'))

    def read_csv(file_name):
        path = os.path.join(DATA_DIR, file_name)
        try:
            with open(path, newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                return list(reader)
        except Exception as e:
            print(f"[ERROR] Could not read {file_name}: {e}")
            return []  # always return a list

    gejala = read_csv('Kode_Gejala_Laptop.csv')
    kerusakan = read_csv('Kode_Kerusakan_Laptop.csv')
    perbaikan = read_csv('Kode_perbaikan_laptop.csv')
    rule_kerusakan = read_csv('Rule_Kerusakan_Laptop.csv')
    rule_perbaikan = read_csv('Rule_perbaikan.csv')

    return render_template('edit_dataset.html',
                           gejala=gejala,
                           kerusakan=kerusakan,
                           perbaikan=perbaikan,
                           rule_kerusakan=rule_kerusakan,
                           rule_perbaikan=rule_perbaikan)


@app.route('/edit-row')
def edit_row():
    dataset = request.args.get('dataset')
    row_id = request.args.get('id')
    # Logic to retrieve the row and show edit form
    return render_template('edit_row.html', dataset=dataset, row_id=row_id)


@app.route('/update_row', methods=['POST'])
def update_row():
    dataset = request.form.get("dataset")  # e.g., "gejala"
    row_id = request.form.get("id")  # first-column value

    # Reconstruct the edited row from form fields
    updated_row = []
    i = 0
    while True:
        val = request.form.get(f"col{i}")
        if val is None:
            break
        updated_row.append(val)
        i += 1

    # Map dataset key → actual CSV path
    dataset_map = {
        "gejala": os.path.join(DATA_DIR, "Kode_Gejala_Laptop.csv"),
        "kerusakan": os.path.join(DATA_DIR, "Kode_Kerusakan_Laptop.csv"),
        "perbaikan": os.path.join(DATA_DIR, "Kode_perbaikan_laptop.csv"),
        "rule_kerusakan": os.path.join(DATA_DIR, "Rule_Kerusakan_Laptop.csv"),
        "rule_perbaikan": os.path.join(DATA_DIR, "Rule_perbaikan.csv"),
    }
    filename = dataset_map.get(dataset)
    if not filename:
        flash("Invalid dataset type.")
        return redirect(url_for("edit_dataset"))

    # Read in all rows, replacing the one that matches row_id
    rows = []
    found = False
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row and row[0] == row_id:
                    rows.append(updated_row)
                    found = True
                else:
                    rows.append(row)
    except FileNotFoundError:
        flash("Data file not found.")
        return redirect(url_for("edit_dataset"))

    if not found:
        flash("Row not found.")
        return redirect(url_for("edit_dataset"))

    # Write the updated data back out
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    flash(f"Successfully updated row in {dataset}.")
    return redirect(url_for("edit_dataset"))


@app.route("/add-row", methods=["POST"])
def add_row():
    dataset = request.form.get("dataset")

    new_row = []
    i = 0
    while True:
        val = request.form.get(f"col{i}")
        if val is None:
            break
        new_row.append(val)
        i += 1

    dataset_map = {
        "gejala": os.path.join(DATA_DIR, "Kode_Gejala_Laptop.csv"),
        "kerusakan": os.path.join(DATA_DIR, "Kode_Kerusakan_Laptop.csv"),
        "perbaikan": os.path.join(DATA_DIR, "Kode_perbaikan_laptop.csv"),
        "rule_kerusakan": os.path.join(DATA_DIR, "Rule_Kerusakan_Laptop.csv"),
        "rule_perbaikan": os.path.join(DATA_DIR, "Rule_perbaikan.csv")
    }

    filename = dataset_map.get(dataset)
    if not filename:
        flash("Invalid dataset.")
        return redirect(url_for("edit_dataset"))

    try:
        with open(filename, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(new_row)
        flash(f"Successfully added row to {dataset}.")
    except Exception as e:
        flash(f"Failed to add row: {str(e)}")

    return redirect(url_for("edit_dataset"))

@app.route("/cekpotensikangker", methods=["GET", "POST"])
def cekpotensikangker():
    model = joblib.load("trainedmodel/cnb_tuned_1diz0q-yanginibagus.joblib")
    features = [
        'Age', 'Gender', 'Air Pollution', 'Alcohol use', 'Dust Allergy',
        'OccuPational Hazards', 'Genetic Risk', 'chronic Lung Disease',
        'Balanced Diet', 'Obesity', 'Smoking', 'Passive Smoker', 'Chest Pain',
        'Coughing of Blood', 'Fatigue', 'Weight Loss', 'Shortness of Breath',
        'Wheezing', 'Swallowing Difficulty', 'Clubbing of Finger Nails',
        'Frequent Cold', 'Dry Cough', 'Snoring'
    ]

    questions = {
        'Age': "Berapa usia Anda saat ini?",
        'Gender': "Apa jenis kelamin Anda?",
        'Air Pollution': "Seberapa sering Anda terpapar polusi udara?",
        'Alcohol use': "Seberapa sering Anda mengonsumsi alkohol?",
        'Dust Allergy': "seberapa sering Anda bereaksi alergi terhadap debu?",
        'OccuPational Hazards': "seberapa sering Anda terpapar bahan kimia?",
        'Genetic Risk': "Apakah ada riwayat kanker paru-paru di keluarga Anda?",
        'chronic Lung Disease': "Apakah Anda memiliki penyakit paru-paru kronis?",
        'Balanced Diet': "Seberapa sering anda makan sehat?",
        'Obesity': "Apakah Anda mengalami kelebihan berat badan?",
        'Smoking': "Seberapa sering Anda merokok?",
        'Passive Smoker': "Seberapa sering Anda terpapar asap rokok dari orang lain?",
        'Chest Pain': "Seberapa sering Anda mengalami nyeri dada?",
        'Coughing of Blood': "Apakah Anda pernah batuk disertai darah?",
        'Fatigue': "Seberapa sering Anda merasa kelelahan?",
        'Weight Loss': "Apakah Anda kehilangan berat badan tanpa sebab yang jelas?",
        'Shortness of Breath': "Seberapa sering Anda mengalami sesak napas?",
        'Wheezing': "Apakah Anda sering bersuara nyaring saat bernapas?",
        'Swallowing Difficulty': "Apakah Anda sering kesulitan menelan makanan?",
        'Clubbing of Finger Nails': "Apakah bentuk kuku Anda membesar atau melengkung?",
        'Frequent Cold': "Seberapa sering Anda terkena flu/pilek?",
        'Dry Cough': "Seberapa sering Anda mengalami batuk kering?",
        'Snoring': "Apakah Anda mendengkur saat tidur?"
    }

    prediction = None
    if request.method == 'POST':
        input_data = [int(request.form[feature]) for feature in features]
        prediction = model.predict([input_data])[0]

    return render_template("cekpotensikangker.html", questions=questions, prediction=prediction)


if __name__ == '__main__':
    app.run(debug=False)

import os
port = int(os.environ.get("PORT", 5000))
app.run(host="0.0.0.0", port=port)
