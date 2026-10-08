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


app = Flask(__name__)

app.secret_key = os.environ.get(
    "NOVA_SECRET_KEY",
    "nevuxa-local-secret-key"
)

app.config["SESSION_PERMANENT"] = False

DATABASE = "nova.db"


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


client = OpenAI(
    api_key=os.environ.get("SPRAG_API_KEY"),
    base_url="https://api.sprag.ai/v1"
)


def calculate_math_expression(expression):
    expression = expression.strip()
    expression = expression.replace(",", "")
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
        raise ValueError("Unsupported characters.")

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

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError("Unsupported operation.")

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError("Invalid number.")

    result = eval(
        compile(tree, "<calculator>", "eval"),
        {"__builtins__": {}},
        {}
    )

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

        if isinstance(result, float):
            if result.is_integer():
                formatted = str(int(result))
            else:
                formatted = str(result)
        else:
            formatted = str(result)

        return (
            "Using Nevuxa AI's calculator:\n\n"
            f"**{formatted}**"
        )

    except Exception:
        return None


@app.route("/")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

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
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]

            return redirect(
                url_for("home")
            )

        return render_template(
            "login.html",
            error="Invalid email or password."
        )

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:
            return render_template(
                "signup.html",
                error="Please enter an email and password."
            )

        hashed_password = generate_password_hash(
            password
        )

        conn = get_db()

        try:
            conn.execute(
                """
                INSERT INTO users (email, password)
                VALUES (?, ?)
                """,
                (
                    email,
                    hashed_password
                )
            )

            conn.commit()
            conn.close()

            return redirect(
                url_for("login")
            )

        except sqlite3.IntegrityError:

            conn.close()

            return render_template(
                "signup.html",
                error="That email is already registered."
            )

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()

    return redirect(
        url_for("login")
    )


@app.route("/chat", methods=["POST"])
def chat():

    if "user_id" not in session:
        return jsonify({
            "error": "Please log in first."
        }), 401

    message = request.form.get(
        "message",
        ""
    ).strip()

    uploaded_file = request.files.get("file")

    if message and not uploaded_file:

        math_answer = try_math_answer(
            message
        )

        if math_answer:
            return jsonify({
                "reply": math_answer
            })

    content = []

    if message:
        content.append({
            "type": "text",
            "text": message
        })

    if uploaded_file:

        filename = uploaded_file.filename or ""

        file_bytes = uploaded_file.read()

        extension = os.path.splitext(
            filename
        )[1].lower()

        if extension in [
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif"
        ]:

            mime_type = (
                uploaded_file.mimetype
                or "image/png"
            )

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

        elif extension in [
            ".txt",
            ".csv",
            ".json"
        ]:

            file_text = file_bytes.decode(
                "utf-8",
                errors="replace"
            )

            content.append({
                "type": "text",
                "text": (
                    f"\n\nFile: {filename}\n"
                    f"{file_text}"
                )
            })

        else:

            return jsonify({
                "error": (
                    "That file type "
                    "is not supported yet."
                )
            }), 400

    if not content:
        return jsonify({
            "error": "Please enter a message."
        }), 400

    system_message = {
        "role": "system",
        "content": (
            "You are Nevuxa AI, a helpful AI assistant. "
            "Always refer to yourself as Nevuxa AI when "
            "your name is relevant. "
            "Give clear, accurate and concise answers. "
            "For exact numerical calculations, do not "
            "guess or invent results. "
            "Explain school-level questions simply "
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

        reply = (
            response
            .choices[0]
            .message
            .content
        )

        return jsonify({
            "reply": reply
        })

    except Exception as e:

        print(
            "SPRAG ERROR:",
            e
        )

        return jsonify({
            "error": (
                "Sorry, Nevuxa AI "
                "couldn't process that request."
            )
        }), 500


@app.route("/run-python", methods=["POST"])
def run_python():

    if "user_id" not in session:
        return jsonify({
            "error": "Please log in first."
        }), 401

    data = request.get_json()

    if not data:
        return jsonify({
            "error": "No code received."
        }), 400

    code = data.get(
        "code",
        ""
    )

    if not isinstance(code, str):
        return jsonify({
            "error": "Invalid code."
        }), 400

    if len(code) > 5000:
        return jsonify({
            "error": "Code is too long."
        }), 400

    try:

        tree = ast.parse(
            code,
            mode="exec"
        )

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

    for node in ast.walk(tree):

        if not isinstance(
            node,
            allowed_nodes
        ):

            return jsonify({
                "error": (
                    "That Python operation "
                    "is not allowed."
                )
            }), 400

    output = io.StringIO()

    safe_globals = {
        "__builtins__": {},
        **allowed_functions
    }

    safe_locals = {}

    try:

        with contextlib.redirect_stdout(
            output
        ):

            exec(
                compile(
                    tree,
                    "<nevuxa-python>",
                    "exec"
                ),
                safe_globals,
                safe_locals
            )

        return jsonify({
            "output": output.getvalue()
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 400


if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
