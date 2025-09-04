import smtplib
import ssl
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
import pandas as pd
import re
import requests
import os
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import random
import string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=10))

# Load BigBasket CSV
df = pd.read_csv("static/data/BigBasket.csv")

# --- OpenRouter API Config ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "Key Not Found")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "mistralai/mistral-7b-instruct"

def get_ingredients_from_ai(recipe: str):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful chef. Return only a list of ingredients as JSON array of strings, no extra text."},
            {"role": "user", "content": f"List the ingredients needed to cook {recipe}"}
        ]
    }
    response = requests.post(OPENROUTER_URL, headers=headers, json=payload)
    data = response.json()
    try:
        raw = data["choices"][0]["message"]["content"]
        ingredients = eval(raw) if raw.strip().startswith("[") else raw.split(",")
        return [ing.strip() for ing in ingredients]
    except Exception as e:
        print("AI parse error:", e, data)
        return []

def search_product(ingredient):
    pattern = re.compile(ingredient, re.IGNORECASE)
    matches = df[df["ProductName"].str.contains(pattern, na=False)]
    if matches.empty:
        return None
    return matches.iloc[0].to_dict()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        recipe = request.form.get("recipe")
        ai_ingredients = get_ingredients_from_ai(recipe)

        cart_items = []
        for ing in ai_ingredients:
            product = search_product(ing)
            if product:
                product["QuantitySelected"] = 0
                cart_items.append(product)

        # ✅ Replace cart with new recipe items
        session["cart"] = cart_items
        session.modified = True

        return redirect(url_for("cart"))

    return render_template("index.html")



@app.route("/cart")
def cart():
    cart_items = session.get("cart", [])
    return render_template("cart.html", cart=cart_items)

@app.route("/update_cart", methods=["POST"])
def update_cart():
    data = request.get_json()
    product_name = data.get("product")
    action = data.get("action")

    cart = session.get("cart", [])
    for item in cart:
        if item["ProductName"] == product_name:
            if action == "add":
                item["QuantitySelected"] += 1
            elif action == "remove" and item["QuantitySelected"] > 0:
                item["QuantitySelected"] -= 1
            break

    session["cart"] = cart
    session.modified = True

    selected = [i for i in cart if i["QuantitySelected"] > 0]
    total_items = sum(i["QuantitySelected"] for i in selected)
    total_cost = sum(float(i["Price"]) * i["QuantitySelected"] for i in selected)

    return jsonify({
        "items": [
            {
                "ProductName": i["ProductName"],
                "Qty": i["QuantitySelected"],
                "Price": float(i["Price"])
            } for i in selected
        ],
        "total_items": total_items,
        "total_cost": total_cost,
        "quantities": {i["ProductName"]: i["QuantitySelected"] for i in cart}
    })

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = session.get("cart", [])
    selected = []

    # convert Price to float
    for i in cart:
        if i["QuantitySelected"] > 0:
            selected.append({
                **i,
                "Price": float(i["Price"])
            })

    total = sum(item["Price"] * item["QuantitySelected"] for item in selected)

    if request.method == "POST":
        session["order"] = {
            "name": request.form["name"],
            "address": request.form["address"],
            "phone": request.form["phone"],
            "email": request.form["email"],
            "info": request.form.get("info", ""),
            "payment": request.form["payment"],
            "cart": selected,
            "total": total
        }
        return redirect(url_for("payment"))  # only GET here

    return render_template("checkout.html", cart=selected, total=total)



@app.route("/payment", methods=["GET"])
def payment():
    order = session.get("order")
    if not order:
        return redirect(url_for("cart"))

    # --- Render email template ---
    html_content = render_template("email.html", order=order)

    # --- Send Email (dummy config for now) ---
    try:
        sender_email = "algorhythm.noreply@gmail.com"
        receiver_email = order["email"]
        password = "qizi jrgq cfdf jyfp"  # for Gmail, generate App Password

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "SmartBasket Order Confirmation"
        msg["From"] = sender_email
        msg["To"] = receiver_email

        # Attach the rendered HTML
        msg.attach(MIMEText(html_content, "html"))

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
    except Exception as e:
        print("❌ Email send failed:", e)

    return render_template("payment.html", order=order)


@app.route("/download_receipt")
def download_receipt():
    order = session.get("order", {})
    if not order:
        return redirect(url_for("checkout"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    story = [Paragraph("SmartBasket Receipt", styles["Title"]), Spacer(1, 20)]
    for item in order["cart"]:
        story.append(Paragraph(f"{item['ProductName']} - {item['QuantitySelected']} x ₹{item['Price']}", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Total: ₹{order['total']}", styles["Heading2"]))
    doc.build(story)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="receipt.pdf", mimetype="application/pdf")

if __name__ == "__main__":
    app.run(debug=True)
