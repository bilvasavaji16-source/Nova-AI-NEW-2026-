import os
import ast
import io
import base64
import sqlite3
import contextlib

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from openai import OpenAI


app = Flask(__name__)


# =========================
# LOGIN SESSION
# =========================

app.secret_key = os.environ.get(
    "NOVA_SECRET_KEY",
    "nova-local-secret-change-later"
)

# Login lasts only while the browser session is open.
app.config["SESSION_PERMANENT"] = False


# =========================
# DATABASE
# =========================

DATABASE = "nova.db"


def get_db():

    connection = sqlite3.connect(DATABASE)

    connection.row_factory = sqlite3.Row

    return connection


def init_database():

    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    connection.commit()

    connection.close()


init_database()


# =========================
# SPRAG
# =========================

client = OpenAI(
    api_key=os.environ.get("SPRAG_API_KEY"),
    base_url="https://api.sprag.ai/v1"
)


# =========================
# HOME
# =========================

@app.route("/")
def home():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "index.html"
    )


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )


        connection = get_db()

        user = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        connection.close()


        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user_id"] = user["id"]

            session["email"] = user["email"]

            return redirect(
                url_for("home")
            )


        return render_template(
            "login.html",
            error="Incorrect email or password."
        )


    return render_template(
        "login.html"
    )


# =========================
# SIGN UP
# =========================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )


        if not email or not password:

            return render_template(
                "signup.html",
                error="Please fill in all fields."
            )


        if password != confirm_password:

            return render_template(
                "signup.html",
                error="The passwords do not match."
            )


        if len(password) < 8:

            return render_template(
                "signup.html",
                error="Password must be at least 8 characters."
            )


        hashed_password = generate_password_hash(
            password
        )


        connection = get_db()


        try:

            cursor = connection.execute(
                """
                INSERT INTO users (email, password)
                VALUES (?, ?)
                """,
                (
                    email,
                    hashed_password
                )
            )

            connection.commit()

            user_id = cursor.lastrowid


        except sqlite3.IntegrityError:

            connection.close()

            return render_template(
                "signup.html",
                error="An account with that email already exists."
            )


        connection.close()


        session["user_id"] = user_id

        session["email"] = email


        return redirect(
            url_for("home")
        )


    return render_template(
        "signup.html"
    )


# =========================
# LOG OUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================
# CHAT
# =========================

@app.route("/chat", methods=["POST"])
def chat():

    if "user_id" not in session:

        return jsonify({
            "reply": "Please sign in first."
        }), 401


    message = request.form.get(
        "message",
        ""
    ).strip()

    file = request.files.get("file")


    if not message and not file:

        return jsonify({
            "reply":
            "Please type a message or attach something."
        })


    try:

        content = []


        if message:

            content.append({
                "type": "text",
                "text": message
            })


        if file:

            filename = file.filename.lower()

            mimetype = file.mimetype


            if mimetype.startswith("image/"):

                image_data = file.read()

                encoded_image = base64.b64encode(
                    image_data
                ).decode("utf-8")


                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url":
                        f"data:{mimetype};base64,{encoded_image}"
                    }
                })


            elif (
                filename.endswith(".txt")
                or filename.endswith(".csv")
                or filename.endswith(".json")
            ):

                file_data = file.read()


                try:

                    text_content = file_data.decode(
                        "utf-8"
                    )

                except UnicodeDecodeError:

                    text_content = file_data.decode(
                        "latin-1"
                    )


                content.append({
                    "type": "text",
                    "text":
                    f"\n\nAttached file: {filename}\n\n"
                    + text_content
                })


            else:

                return jsonify({
                    "reply":
                    "Nova doesn't support this file type yet."
                })


        response = client.chat.completions.create(

            model="symphony",

            messages=[

                {
                    "role": "system",
                    "content":
                    "You are Nova AI, a helpful and friendly AI assistant."
                },

                {
                    "role": "user",
                    "content": content
                }

            ]
        )


        reply = response.choices[0].message.content


        return jsonify({
            "reply": reply
        })


    except Exception as e:

        print(
            "Sprag error:",
            e
        )


        return jsonify({
            "reply":
            "Sorry, Nova couldn't process that request."
        })


# =========================
# PYTHON RUNNER
# =========================

@app.route("/run-python", methods=["POST"])
def run_python():

    if "user_id" not in session:

        return jsonify({
            "output": "Please sign in first."
        }), 401


    data = request.get_json()

    code = data.get(
        "code",
        ""
    )


    if not code.strip():

        return jsonify({
            "output": "No code entered."
        })


    allowed_nodes = (
        ast.Module,
        ast.Expr,
        ast.Assign,
        ast.Name,
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
        ast.Load,
        ast.Store,
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
        ast.BoolOp,
        ast.And,
        ast.Or,
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


    try:

        tree = ast.parse(
            code,
            mode="exec"
        )


        for node in ast.walk(tree):

            if not isinstance(
                node,
                allowed_nodes
            ):

                return jsonify({
                    "output":
                    "That Python feature isn't allowed in Nova's safe runner yet."
                })


            if isinstance(
                node,
                ast.Call
            ):

                if not (
                    isinstance(
                        node.func,
                        ast.Name
                    )
                    and
                    node.func.id
                    in allowed_functions
                ):

                    return jsonify({
                        "output":
                        "That function isn't allowed in Nova's safe runner."
                    })


        compiled = compile(
            tree,
            "<nova-python>",
            "exec"
        )


        output_buffer = io.StringIO()


        safe_globals = {
            "__builtins__": {},
            **allowed_functions
        }


        with contextlib.redirect_stdout(
            output_buffer
        ):

            exec(
                compiled,
                safe_globals,
                safe_globals
            )


        output = output_buffer.getvalue()


        if not output:

            output = "Code finished successfully."


        return jsonify({
            "output": output
        })


    except Exception as e:

        return jsonify({
            "output":
            f"Python error: {e}"
        })


# =========================
# START NOVA
# =========================

if __name__ == "__main__":

    app.run(
        debug=True
    )
