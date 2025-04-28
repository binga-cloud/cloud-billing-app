from flask import Flask, render_template, request, redirect, session, flash, g, url_for
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DATABASE = 'billing.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

if not os.path.exists(DATABASE):
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE billing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                year TEXT NOT NULL,
                month TEXT NOT NULL,
                company_name TEXT NOT NULL,
                service TEXT NOT NULL,
                amount_usd REAL NOT NULL,
                conversion_rate REAL NOT NULL,
                amount_bdt REAL NOT NULL,
                service_charge REAL NOT NULL,
                vat REAL NOT NULL,
                total_bdt REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                value TEXT NOT NULL,
                UNIQUE(type, value)
            )
        """)

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = 'admin' if user_count == 0 else 'monitor'
        db.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
        db.commit()
        flash(f'Registered successfully as {role}.')
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            return redirect('/dashboard')
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/entry', methods=['GET', 'POST'])
def entry():
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()

    if request.method == 'POST':
        for field in ['provider', 'year', 'month', 'company', 'service']:
            if f'new_{field}' in request.form and request.form[f'new_{field}']:
                db.execute("INSERT OR IGNORE INTO metadata (type, value) VALUES (?, ?)", (field, request.form[f'new_{field}']))

        provider = request.form.get('new_provider') or request.form.get('provider')
        year = request.form.get('new_year') or request.form.get('year')
        month = request.form.get('new_month') or request.form.get('month')
        company = request.form.get('new_company') or request.form.get('company')
        service = request.form.get('new_service') or request.form.get('service')

        amount_usd = float(request.form['amount_usd'])
        conversion_rate = float(request.form['conversion_rate'])
        amount_bdt = amount_usd * conversion_rate
        service_charge = round(amount_bdt * 0.07, 1)
        vat = round((amount_bdt + service_charge) * 0.05, 1)
        total_bdt = amount_bdt + service_charge + vat

        db.execute("""
            INSERT INTO billing (
                provider, year, month, company_name, service,
                amount_usd, conversion_rate, amount_bdt,
                service_charge, vat, total_bdt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (provider, year, month, company, service, amount_usd, conversion_rate, amount_bdt, service_charge, vat, total_bdt))
        db.commit()
        flash('Entry submitted successfully!', 'success')
        return redirect('/entry')

    metadata = db.execute("SELECT type, value FROM metadata").fetchall()
    data = {
        'providers': sorted({v for t, v in metadata if t == 'provider'}),
        'years': sorted({v for t, v in metadata if t == 'year'}),
        'months': sorted({v for t, v in metadata if t == 'month'}),
        'companies': sorted({v for t, v in metadata if t == 'company'}),
        'services': sorted({v for t, v in metadata if t == 'service'})
    }

    return render_template('entry.html', **data)

@app.route('/edit/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(entry_id):
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()

    if request.method == 'POST':
        provider = request.form['provider']
        year = request.form['year']
        month = request.form['month']
        company_name = request.form['company_name']
        service = request.form['service']
        amount_usd = float(request.form['amount_usd'])
        conversion_rate = float(request.form['conversion_rate'])

        amount_bdt = amount_usd * conversion_rate
        service_charge = round(amount_bdt * 0.07, 1)
        vat = round((amount_bdt + service_charge) * 0.05, 1)
        total_bdt = amount_bdt + service_charge + vat

        db.execute("""
            UPDATE billing SET 
                provider = ?, 
                year = ?, 
                month = ?, 
                company_name = ?, 
                service = ?, 
                amount_usd = ?, 
                conversion_rate = ?, 
                amount_bdt = ?, 
                service_charge = ?, 
                vat = ?, 
                total_bdt = ?
            WHERE id = ?
        """, (provider, year, month, company_name, service, amount_usd, conversion_rate, amount_bdt, service_charge, vat, total_bdt, entry_id))
        db.commit()
        flash('Entry updated successfully.')
        return redirect('/report')

    entry = db.execute("SELECT * FROM billing WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        flash('Entry not found')
        return redirect('/report')

    return render_template('edit_entry.html', entry=entry)

@app.route('/delete/<int:entry_id>', methods=['POST'])
def delete_entry(entry_id):
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()
    db.execute("DELETE FROM billing WHERE id = ?", (entry_id,))
    db.commit()
    flash('Entry deleted successfully.')
    return redirect('/report')

@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()
    query = "SELECT * FROM billing WHERE 1=1"
    params = []

    provider = request.args.get('provider')
    service = request.args.get('service')
    month = request.args.get('month')

    if provider:
        query += " AND provider = ?"
        params.append(provider)
    if service:
        query += " AND service = ?"
        params.append(service)
    if month:
        query += " AND month = ?"
        params.append(month)

    results = db.execute(query, params).fetchall()

    total = sum(row[11] for row in results) if results else 0
    services = sorted(set(row[0] for row in db.execute("SELECT service FROM billing").fetchall()))
    months = sorted(set(row[0] for row in db.execute("SELECT month FROM billing").fetchall()))

    return render_template('report.html', results=results, total=total, services=services, months=months)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()
    azure_total = db.execute("SELECT SUM(total_bdt) FROM billing WHERE provider = 'Azure'").fetchone()[0] or 0
    gcp_total = db.execute("SELECT SUM(total_bdt) FROM billing WHERE provider = 'GCP'").fetchone()[0] or 0

    return render_template('dashboard.html', azure_total=azure_total, gcp_total=gcp_total)

@app.route('/users', methods=['GET', 'POST'])
def users():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    db = get_db()

    if request.method == 'POST':
        user_id = request.form['user_id']
        new_role = request.form['role']
        db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        db.commit()
        flash('User role updated.')

    users = db.execute("SELECT id, username, role FROM users").fetchall()
    return render_template('users.html', users=users)

if __name__ == '__main__':
    app.run(debug=True)