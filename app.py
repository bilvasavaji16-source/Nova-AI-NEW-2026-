
import os
import ast
import io
import base64
import sqlite3
import contextlib
import re

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from openai import OpenAI


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get("NOVA_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "Set the NOVA_SECRET_KEY environment variable before running."
    )

app.config["SESSION_PERMANENT"] = False


# ============================================================
# DATABASE
# ============================================================

DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "nova.db"
)


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# AI CLIENT
# ============================================================

api_key = os.environ.get("SPRAG_API_KEY")

client = (
    OpenAI(
        api_key=api_key,
        base_url="https://api.sprag.ai/v1"
    )
    if api_key
    else None
)


# ============================================================
# SMART MATH CALCULATOR
# ============================================================

def calculate_math_expression(expression):
    expression = expression.strip().replace(",", "")

    expression = expression.replace("×", "*")
    expression = expression.replace("÷", "/")
    expression = expression.replace("−", "-")

    expression = re.sub(
        r"(\d+(?:\.\d+)?)%",
        r"(\1/100)",
        expression
    )

    if not re.fullmatch(
        r"[0-9\s\.\+\-\*\/%\(\)]+",
        expression
    ):
        raise ValueError("Unsupported characters in expression.")

    tree = ast.parse(expression, mode="eval")

    allowed_nodes = (
        ast.Expression,
        ast.Constant,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd
    )

    nodes = list(ast.walk(tree))

    if len(nodes) > 100:
        raise ValueError("Expression is too long.")

    for node in nodes:
        if not isinstance(node, allowed_nodes):
            raise ValueError("Unsupported math operation.")

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError("Invalid number.")

            if abs(node.value) > 10**12:
                raise ValueError("Number is too long.")

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not isinstance(node.right, ast.Constant):
                raise ValueError("Use a simple exponent.")

            if not isinstance(node.right.value, (int, float)):
                raise ValueError("Invalid exponent.")

            if abs(node.right.value) > 100:
                raise ValueError("Exponent is too large.")

    result = eval(
        compile(tree, "<calculator>", "eval"),
        {"__builtins__": {}},
        {}
    )

    if not isinstance(result, (int, float)):
        raise ValueError("Invalid result.")

    if abs(result) > 10**100:
        raise ValueError("Result is too large.")

    return result


def try_math_answer(message):
    text = message.strip()

    text = re.sub(
        r"^(calculate|compute|solve|what is|what's)\s+",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = text.rstrip("?").strip()

    if not re.search(r"\d", text):
        return None

    if not re.search(r"[\+\-\*\/×÷%]", text):
        return None

    try:
        result = calculate_math_expression(text)

        if isinstance(result, float) and result.is_integer():
            formatted = str(int(result))
        else:
            formatted = str(result)

        return (
            "Using Nevuxa's calculator:\n\n"
            f"**{formatted}**"
        )

    except Exception:
        return None


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("index.html")


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]

            return redirect(url_for("home"))

        return render_template(
            "login.html",
            error="Invalid email or password."
        )

    return render_template("login.html")


# ============================================================
# SIGNUP
# ============================================================

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not email or not password or not confirm_password:
            return render_template(
                "signup.html",
                error="Please fill in all the fields."
            )

        # SERVER-SIDE PASSWORD CONFIRMATION
        if password != confirm_password:
            return render_template(
                "signup.html",
                error="Passwords do not match."
            )

        if len(password) < 8:
            return render_template(
                "signup.html",
                error="Password must be at least 8 characters long."
            )

        hashed_password = generate_password_hash(password)

        conn = get_db()

        try:
            conn.execute(
                """
                INSERT INTO users (email, password)
                VALUES (?, ?)
                """,
                (email, hashed_password)
            )

            conn.commit()
            conn.close()

            return redirect(url_for("login"))

        
        except sqlite3.IntegrityError:
            conn.close()

            return render_template(
                "signup.html",
                error="This email is already registered. If you need help, please contact your support email at  Bilvasavaji16@gmail.com."
            )

            )

    return render_template("signup.html")

# ============================================================
# TERMS & CONDITIONS
# ============================================================

@app.route("/terms")
def terms():
    return render_template("terms.html")


# ============================================================
# PRIVACY POLICY
# ============================================================

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ============================================================
# LOG OUT
# ============================================================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# MY ACCOUNT
# ============================================================

@app.route("/account")
def account():https://www.youtube.com/watch?v=X8TtiJ7HbWE
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "account.html",
        email=session.get("user_email", "")
    )


# ============================================================
# CHANGE PASSWORD
# ============================================================

@app.route("/change-password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get(
        "confirm_password",
        ""
    )

    if not new_password or not confirm_password:
        return render_template(
            "account.html",
            email=session.get("user_email", ""),
            error="Please complete all the fields."
        )

    if new_password != confirm_password:
        return render_template(
            "account.html",
            email=session.get("user_email", ""),
            error="New passwords do not match."
        )

    if len(new_password) < 6:
        return render_template(
            "account.html",
            email=session.get("user_email", ""),
            error="New password must be at least 6 characters long."
        )

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not user or not check_password_hash(
        user["password"],
        current_password
    ):
        conn.close()

        return render_template(
            "account.html",
            email=session.get("user_email", ""),
            error="Current password is incorrect."
        )

    hashed_password = generate_password_hash(new_password)

    conn.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (hashed_password, session["user_id"])
    )

    conn.commit()
    conn.close()

    return render_template(
        "account.html",
        email=session.get("user_email", ""),
        success="Password was changed successfully."
    )


# ============================================================
# CHAT
# ============================================================

@app.route("/chat", methods=["POST"])
def chat():
    if "user_id" not in session:
        return jsonify({
            "error": "Please log in first."
        }), 401

    message = request.form.get("message", "").strip()
    uploaded_file = request.files.get("file")

    if message and not uploaded_file:
        math_answer = try_math_answer(message)

        if math_answer:
            return jsonify({"reply": math_answer})

    content = []

    if message:
        content.append({
            "type": "text",
            "text": message
        })

    if uploaded_file and uploaded_file.filename:
        filename = uploaded_file.filename
        file_bytes = uploaded_file.read()

       
        if len(file_bytes) > 60 * 1024 * 1024:
            return jsonify({
                "error": "Files must be 60 MB or smaller."
            }), 413


        extension = os.path.splitext(filename)[1].lower()

        if extension in [
            ".png", ".jpg", ".jpeg", ".webp", ".gif"
        ]:
            mime_type = uploaded_file.mimetype or "image/png"

            encoded = base64.b64encode(
                file_bytes
            ).decode("utf-8")

            content.append({
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{mime_type};"
                        f"base64,{encoded}"
                    )
                }
            })

        elif extension in [".txt", ".csv", ".json"]:
            file_text = file_bytes.decode(
                "utf-8",
                errors="replace"
            )

            content.append({
                "type": "text",
                "text": f"\n\nFile: {filename}\n{file_text}"
            })

        else:
            return jsonify({
                "error": "That file type is not supported yet."
            }), 400

    if not content:
        return jsonify({
            "error": "Please enter a message."
        }), 400

    if client is None:
        return jsonify({
            "error": "AI service is not configured. Please contact Bilvasavaji16@gmail.com for support."
        }), 503

    system_message = {
        "role": "system",
        "content": (
            "You are Nevuxa, a helpful AI assistant. "
            "Give clear, accurate and concise answers. "
            "For exact numerical calculations, do not invent "
            "results. Explain school-level questions simply "
            "when appropriate."
        )
    }

    user_message = {
        "role": "user",
        "content": content
    }

    try:
        response = client.chat.completions.create(
            model="symphony",
            messages=[
                system_message,
                user_message
            ]
        )

        reply = response.choices[0].message.content

        return jsonify({"reply": reply})

    except Exception as e:
        app.logger.error("Nevuxa AI request failed: %s", e)

        return jsonify({
            "error": (
                "Sorry, Nevuxa couldn't process that request. "
                "If you want to troubleshoot, email Bilvasavaji16@gmail.com for problems."
            )
        }), 500


# ============================================================
# PYTHON RUNNER
# ============================================================
# IMPORTANT:
# AST restrictions alone are NOT a secure sandbox for running
# arbitrary code on a public server. Use an isolated execution
# service with resource limits before enabling this publicly.

@app.route("/run-python", methods=["POST"])
def run_python():
    if "user_id" not in session:
        return jsonify({
            "error": "Please log in first."
        }), 401

    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "No code received."}), 400

    code = data.get("code", "")

    if not isinstance(code, str):
        return jsonify({"error": "Invalid code."}), 400

    if len(code) > 5000:
        return jsonify({"error": "Code is too long."}), 400

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return jsonify({
            "error": f"Syntax error: {e}"
        }), 400

    allowed_nodes = (
        ast.Module,
        ast.Expr,
        ast.Assign,
        ast.Name,
        ast.Load,
        ast.Store,
        ast.Constant,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Call,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.If,
        ast.IfExp
    )

    allowed_functions = {
        "print": print,
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "sum": sum,
        "min": min,
        "max": max,
        "abs": abs
    }

    if len(list(ast.walk(tree))) > 500:
        return jsonify({
            "error": "Code is too complex."
        }), 400

    assigned_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Store)
    }

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            return jsonify({
                "error": "That Python operation is not allowed."
            }), 400

        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                if (
                    node.id not in allowed_functions
                    and node.id not in assigned_names
                ):
                    return jsonify({
                        "error": f"Name '{node.id}' is not allowed."
                    }), 400

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not isinstance(node.right, ast.Constant):
                return jsonify({
                    "error": "Only simple exponents are allowed."
                }), 400

            if (
                not isinstance(node.right.value, (int, float))
                or abs(node.right.value) > 10
            ):
                return jsonify({
                    "error": "Exponent is too large."
                }), 400

    output = io.StringIO()

    safe_globals = {
        "__builtins__": {},
        **allowed_functions
    }

    safe_locals = {}

    try:
        with contextlib.redirect_stdout(output):
            exec(
                compile(tree, "<nevuxa-python>", "exec"),
                safe_globals,
                safe_locals
            )

        return jsonify({
            "output": output.getvalue()[:20000]
        })

    except Exception:
        return jsonify({
            "error": "The code could not be completed."
        }), 400


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
