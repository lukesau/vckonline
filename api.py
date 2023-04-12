from flask import Flask, redirect, url_for, render_template, session, request, copy_current_request_context, jsonify
from datetime import timedelta
import os
from basegame import *


import flask

app = flask.Flask(__name__)
app.config["DEBUG"] = True
app.secret_key = "hi"
playerNameList = []

@app.route('/', methods=['GET'])
def home():
    return "<a href=\"login\">Login</a>"

@app.route('/playerlist', methods=['GET'])
def playerlist():
    fuckyou = json.dumps(playerNameList)
    print(fuckyou)
    return fuckyou

@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == "POST":
        session.permanent = True  # <--- makes the permanent session
        user = request.form["nm"]
        session["name"] = user
        playerNameList.append(user)
        return redirect(url_for("playerlist"))
    else:
        if "name" in session:
            return redirect(url_for("playerlist"))

        return render_template("login.html")

@app.route("/user")
def user():
    if "user" in session:
        user = session["user"]
        return f"<h1>{user}</h1>"
    else:
        return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))



app.run(debug=True, host='0.0.0.0')
