# ============================================================
# ESP32 MicroPython — Дистанционно управление на реле + 2 входа
# Уеб интерфейс с автоматично обновяване на статуса (1 сек)
# ============================================================

import network
import socket
import json
import time
from machine import Pin

# ---------------- КОНФИГУРАЦИЯ ----------------
WIFI_SSID = ""
WIFI_PASS = ""

RELAY_PIN = 26          # Изход за релето
RELAY_ACTIVE_LOW = False  # True ако релейният модул се активира с LOW

INPUT1_PIN = 32         # Вход 1 (само индикация)
INPUT2_PIN = 33         # Вход 2 (само индикация)
INPUT_ACTIVE_LOW = True   # True = активен при затваряне към GND (pull-up)

LED_PIN = 2             # Вграден LED — свети при активна WiFi връзка

INPUT1_NAME = "Вход 1"
INPUT2_NAME = "Вход 2"

# ---------------- ХАРДУЕР ----------------
relay = Pin(RELAY_PIN, Pin.OUT)
led = Pin(LED_PIN, Pin.OUT)

if INPUT_ACTIVE_LOW:
    in1 = Pin(INPUT1_PIN, Pin.IN, Pin.PULL_UP)
    in2 = Pin(INPUT2_PIN, Pin.IN, Pin.PULL_UP)
else:
    in1 = Pin(INPUT1_PIN, Pin.IN, Pin.PULL_DOWN)
    in2 = Pin(INPUT2_PIN, Pin.IN, Pin.PULL_DOWN)

relay_state = False  # логическо състояние (True = включено)


def apply_relay():
    """Прилага логическото състояние към физическия пин."""
    if RELAY_ACTIVE_LOW:
        relay.value(0 if relay_state else 1)
    else:
        relay.value(1 if relay_state else 0)


def read_input(pin):
    """Връща True ако входът е активен, съобразено с полярността."""
    v = pin.value()
    return (v == 0) if INPUT_ACTIVE_LOW else (v == 1)


apply_relay()  # изходно състояние: изключено

# ---------------- WIFI ----------------
def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    print("Свързване към WiFi...")
    wlan.connect(WIFI_SSID, WIFI_PASS)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > 15000:
            print("Неуспешно свързване, рестарт на WiFi...")
            wlan.active(False)
            time.sleep(1)
            wlan.active(True)
            wlan.connect(WIFI_SSID, WIFI_PASS)
            t0 = time.ticks_ms()
        time.sleep_ms(200)
    led.value(1)
    print("Свързан! IP:", wlan.ifconfig()[0])
    return wlan


# ---------------- HTML СТРАНИЦА ----------------
HTML = """<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 Реле</title>
<style>
  body { background:#1a1d23; color:#e6e6e6; font-family:sans-serif;
         display:flex; flex-direction:column; align-items:center; padding:24px; }
  h1 { font-size:1.3em; color:#7ecbff; }
  .card { background:#242832; border-radius:12px; padding:20px 28px;
          margin:10px; min-width:260px; text-align:center;
          box-shadow:0 2px 8px rgba(0,0,0,.4); }
  button { font-size:1.2em; padding:14px 40px; border:none; border-radius:10px;
           cursor:pointer; color:#fff; transition:background .2s; }
  .on  { background:#2e9e5b; }
  .off { background:#555c68; }
  .ind { display:inline-block; width:18px; height:18px; border-radius:50%;
         margin-right:10px; vertical-align:middle; }
  .ind.active   { background:#3ddc84; box-shadow:0 0 10px #3ddc84; }
  .ind.inactive { background:#3a3f4a; }
  .row { margin:10px 0; font-size:1.1em; text-align:left; }
  #conn { font-size:.85em; color:#888; margin-top:14px; }
</style>
</head>
<body>
<h1>ESP32 — Управление на реле</h1>

<div class="card">
  <button id="btn" class="off" onclick="toggleRelay()">РЕЛЕ: ---</button>
</div>

<div class="card">
  <div class="row"><span id="i1" class="ind inactive"></span><span id="n1">Вход 1</span></div>
  <div class="row"><span id="i2" class="ind inactive"></span><span id="n2">Вход 2</span></div>
</div>

<div id="conn">свързване...</div>

<script>
async function refresh(){
  try{
    const r = await fetch('/api/status');
    const d = await r.json();
    const btn = document.getElementById('btn');
    btn.textContent = 'РЕЛЕ: ' + (d.relay ? 'ВКЛ' : 'ИЗКЛ');
    btn.className = d.relay ? 'on' : 'off';
    document.getElementById('i1').className = 'ind ' + (d.in1 ? 'active' : 'inactive');
    document.getElementById('i2').className = 'ind ' + (d.in2 ? 'active' : 'inactive');
    document.getElementById('n1').textContent = d.n1;
    document.getElementById('n2').textContent = d.n2;
    document.getElementById('conn').textContent = 'онлайн';
  }catch(e){
    document.getElementById('conn').textContent = 'няма връзка...';
  }
}
async function toggleRelay(){
  try{ await fetch('/api/relay?state=toggle'); refresh(); }catch(e){}
}
setInterval(refresh, 1000);
refresh();
</script>
</body>
</html>
"""


# ---------------- HTTP СЪРВЪР ----------------
def send_response(conn, status, ctype, body):
    if isinstance(body, str):
        body = body.encode("utf-8")
    conn.send("HTTP/1.1 {}\r\nContent-Type: {}; charset=utf-8\r\n"
              "Content-Length: {}\r\nConnection: close\r\n\r\n"
              .format(status, ctype, len(body)))
    conn.send(body)


def handle_request(conn):
    global relay_state
    try:
        req = conn.recv(1024).decode("utf-8", "ignore")
        if not req:
            return
        line = req.split("\r\n", 1)[0]
        parts = line.split(" ")
        path = parts[1] if len(parts) > 1 else "/"

        if path.startswith("/api/status"):
            data = {
                "relay": relay_state,
                "in1": read_input(in1),
                "in2": read_input(in2),
                "n1": INPUT1_NAME,
                "n2": INPUT2_NAME,
            }
            send_response(conn, "200 OK", "application/json", json.dumps(data))

        elif path.startswith("/api/relay"):
            if "state=on" in path:
                relay_state = True
            elif "state=off" in path:
                relay_state = False
            elif "state=toggle" in path:
                relay_state = not relay_state
            apply_relay()
            send_response(conn, "200 OK", "application/json",
                          json.dumps({"relay": relay_state}))

        elif path == "/" or path.startswith("/index"):
            send_response(conn, "200 OK", "text/html", HTML)

        else:
            send_response(conn, "404 Not Found", "text/plain", "404")
    except Exception as e:
        print("Грешка при заявка:", e)
    finally:
        conn.close()


def main():
    wlan = wifi_connect()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 80))
    s.listen(3)
    s.settimeout(2)
    print("Сървърът работи на http://{}/".format(wlan.ifconfig()[0]))

    while True:
        # следене на WiFi връзката
        if not wlan.isconnected():
            led.value(0)
            wlan = wifi_connect()

        try:
            conn, addr = s.accept()
        except OSError:
            continue  # timeout — цикълът продължава и проверява WiFi
        handle_request(conn)


main()
