"""
robot_wifi_v2.py — Raspberry Pi 3 (Thonny)
Chaise roulante autonome : WiFi + Vosk + Fuzzy + Sécurité obstacles
Sur le PC : send_audio_pc.py  |  Sur le Pi : ce fichier
"""

import RPi.GPIO as GPIO
import socket, threading, time, random, json
from vosk import Model, KaldiRecognizer
from simpful import FuzzySystem, FuzzySet, LinguisticVariable

# ═══════ CONFIGURATION ═══════

IN1, IN2, IN3, IN4 = 23, 24, 27, 22
ENA, ENB = 18, 19
TRIG_FRONT, ECHO_FRONT = 20, 14
TRIG_BACK,  ECHO_BACK  = 16, 12

BTN_PINS = {"forward": 5, "backward": 6, "left": 13, "right": 26, "stop": 21}

DIST_CRITICAL, DIST_DANGER, DIST_WARN, DIST_MAX = 10, 15, 30, 300
SPEED_NORMAL, SPEED_SLOW, KICK_DURATION = 85, 65, 0.09
PWM_FREQ = 1000

UDP_PORT, BUFFER, TARGET_SR = 5005, 4096, 16000
MODEL_PATH = "/home/pi/model"
VOCAB = ('["avance","avancer","recule","reculer","gauche","droite",'
         '"stop","arret","auto","automatique","manuel","[unk]"]')

# Directions moteur : (IN1, IN2, IN3, IN4)
MOTOR_DIRS = {
    "forward":  (1, 0, 1, 0),
    "backward": (0, 1, 0, 1),
    "left":     (1, 0, 0, 1),
    "right":    (0, 1, 1, 0),
}

# Mapping voix française → commande moteur
VOICE_MAP = {
    "avance": "forward", "avancer": "forward",
    "recule": "backward", "reculer": "backward",
    "gauche": "left", "droite": "right",
}

# Commandes autorisées selon l'état obstacle
ALLOWED_CMDS = {
    "clear":         {"forward", "backward", "left", "right", "stop"},
    "front_blocked": {"backward", "left", "right", "stop"},
    "back_blocked":  {"forward", "left", "right", "stop"},
    "both_blocked":  {"left", "right", "stop"},
}


# ═══════ ÉTAT GLOBAL (thread-safe) ═══════

_state = {"mode": "idle", "voice_cmd": "stop", "btn_latch": "stop", "stop_flag": False}
_lock  = threading.Lock()


def sget(key):
    with _lock: return _state[key]


def sset(key, val):
    with _lock: _state[key] = val


def set_mode(mode):
    with _lock:
        _state.update(mode=mode, voice_cmd="stop", btn_latch="stop", stop_flag=False)
    print(f"\n[MODE] ══ {mode.upper()} ══")


def check_and_clear_stop():
    with _lock:
        if _state["stop_flag"]:
            _state.update(stop_flag=False, voice_cmd="stop", btn_latch="stop")
            return True
        return False


# ═══════ GPIO + PWM ═══════

_pwmA = _pwmB = None


def setup_gpio():
    global _pwmA, _pwmB
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    for pin in (IN1, IN2, IN3, IN4, ENA, ENB, TRIG_FRONT, TRIG_BACK):
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    for pin in (ECHO_FRONT, ECHO_BACK):
        GPIO.setup(pin, GPIO.IN)
    for pin in BTN_PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    _pwmA = GPIO.PWM(ENA, PWM_FREQ)
    _pwmB = GPIO.PWM(ENB, PWM_FREQ)
    _pwmA.start(0)
    _pwmB.start(0)
    print("[GPIO+PWM] OK")


# ═══════ MOTEURS (drive unifié + kick de démarrage) ═══════

_current_dir = None


def motor_stop():
    global _current_dir
    _current_dir = None
    _pwmA.ChangeDutyCycle(0)
    _pwmB.ChangeDutyCycle(0)
    for pin in (IN1, IN2, IN3, IN4):
        GPIO.output(pin, 0)


def drive(direction, speed=None):
    global _current_dir
    if direction not in MOTOR_DIRS:
        motor_stop(); return

    speed = speed or SPEED_NORMAL
    for pin, val in zip((IN1, IN2, IN3, IN4), MOTOR_DIRS[direction]):
        GPIO.output(pin, val)

    # Kick à 100% uniquement lors d'un changement de direction
    if _current_dir != direction:
        _pwmA.ChangeDutyCycle(100)
        _pwmB.ChangeDutyCycle(100)
        time.sleep(KICK_DURATION)
        _current_dir = direction

    _pwmA.ChangeDutyCycle(speed)
    _pwmB.ChangeDutyCycle(speed)


def apply_cmd(cmd, speed=None):
    drive(cmd, speed) if cmd in MOTOR_DIRS else motor_stop()


# ═══════ CAPTEURS ULTRASON ═══════

def _single_measure(trig, echo):
    GPIO.output(trig, True)
    time.sleep(1e-5)
    GPIO.output(trig, False)

    timeout = time.time()
    while not GPIO.input(echo):
        if time.time() - timeout > 0.02: return DIST_MAX

    start = end = time.time()
    while GPIO.input(echo):
        end = time.time()
        if end - start > 0.02: return DIST_MAX

    d = (end - start) * 17150
    return round(d, 2) if 2 < d < DIST_MAX else DIST_MAX


def measure(trig, echo):
    return sorted(_single_measure(trig, echo) for _ in range(3))[1]


# ═══════ LOGIQUE FLOUE ═══════

def _build_fuzzy():
    fs = FuzzySystem()
    fs.add_linguistic_variable("Distance", LinguisticVariable([
        FuzzySet(points=[[0,1],[15,1],[20,0]], term="proche"),
        FuzzySet(points=[[15,0],[22,1],[30,0]], term="critique"),
        FuzzySet(points=[[25,0],[50,1],[100,1]], term="loin"),
    ], universe_of_discourse=[0, 100]))
    fs.add_linguistic_variable("Vitesse", LinguisticVariable([
        FuzzySet(points=[[0,1],[0,1],[10,0]], term="arret"),
        FuzzySet(points=[[5,0],[30,1],[55,0]], term="lent"),
        FuzzySet(points=[[45,0],[80,1],[100,1]], term="normal"),
    ], universe_of_discourse=[0, 100]))
    fs.add_rules([
        "IF (Distance IS proche) THEN (Vitesse IS arret)",
        "IF (Distance IS critique) THEN (Vitesse IS lent)",
        "IF (Distance IS loin) THEN (Vitesse IS normal)",
    ])
    return fs

_FS = _build_fuzzy()


def fuzzy_speed(distance):
    try:
        _FS.set_variable("Distance", max(0.0, min(float(distance), 100.0)))
        return _FS.Mamdani_inference(["Vitesse"])["Vitesse"]
    except Exception:
        return 0.0 if distance < DIST_WARN else 100.0


# ═══════ OBSTACLES ═══════

def get_obs_state(front, back):
    f_blk, b_blk = front <= DIST_DANGER, back <= DIST_DANGER
    if f_blk and b_blk: return "both_blocked"
    if f_blk: return "front_blocked"
    if b_blk: return "back_blocked"
    return "clear"


def filter_cmd(cmd, obs):
    if cmd in ALLOWED_CMDS[obs]:
        return cmd
    if cmd not in ("stop", None, ""):
        print(f"[SECURITE] '{cmd}' interdit [{obs}]")
    return "stop"


# ═══════ ÉVITEMENT (mode auto) ═══════

def scan_and_choose():
    drive("left");  time.sleep(0.5)
    dl = measure(TRIG_FRONT, ECHO_FRONT)
    motor_stop();   time.sleep(0.05)
    drive("right"); time.sleep(1.0)
    dr = measure(TRIG_FRONT, ECHO_FRONT)
    motor_stop();   time.sleep(0.05)
    drive("left");  time.sleep(0.5)
    motor_stop()
    print(f"[SCAN] G:{dl:.0f}cm D:{dr:.0f}cm")
    if dl < DIST_WARN and dr < DIST_WARN:
        return "backward"
    return "left" if dl >= dr else "right"


def execute_avoidance(direction, back):
    if direction in ("left", "right"):
        drive(direction); time.sleep(0.7); motor_stop()
    elif direction == "backward" and back > DIST_DANGER:
        drive("backward"); time.sleep(0.5); motor_stop()
        drive(random.choice(["left", "right"])); time.sleep(0.7); motor_stop()
    else:
        print("[BLOCAGE] Bloque des deux cotes"); motor_stop()


# ═══════ BOUTONS LATCH (front descendant) ═══════

_prev_btns = {cmd: GPIO.HIGH for cmd in BTN_PINS}


def poll_buttons(obs):
    global _prev_btns

    # STOP — prioritaire tous modes
    cur = GPIO.input(BTN_PINS["stop"])
    if cur == GPIO.LOW and _prev_btns["stop"] == GPIO.HIGH:
        sset("btn_latch", "stop")
        sset("voice_cmd", "stop")
        print("[BTN] STOP")
    _prev_btns["stop"] = cur

    # Directionnels — mode manuel uniquement
    if sget("mode") == "manuel":
        for cmd in ("forward", "backward", "left", "right"):
            cur = GPIO.input(BTN_PINS[cmd])
            if cur == GPIO.LOW and _prev_btns[cmd] == GPIO.HIGH:
                filtered = filter_cmd(cmd, obs)
                sset("btn_latch", filtered)
                print(f"[BTN] {cmd} -> latch={filtered}")
            _prev_btns[cmd] = cur

    return sget("btn_latch")


# ═══════ VOIX (UDP + Vosk) ═══════

def handle_voice(text):
    print(f"[VOIX] '{text}'")

    # STOP haute priorité — tous modes
    if "stop" in text or "arret" in text:
        with _lock:
            _state.update(stop_flag=True, voice_cmd="stop", btn_latch="stop")
        print("[VOIX] STOP HAUTE PRIORITE"); return

    # Changement de mode
    if "auto" in text or "automatique" in text:
        set_mode("auto"); return
    if "manuel" in text:
        set_mode("manuel")

    # Commandes directionnelles via dictionnaire
    if sget("mode") == "manuel":
        for keyword, cmd in VOICE_MAP.items():
            if keyword in text:
                sset("voice_cmd", cmd)
                print(f"[VOIX] -> {cmd}"); return


def udp_vosk_thread():
    print("[VOSK] Chargement du modele...")
    rec = KaldiRecognizer(Model(MODEL_PATH), TARGET_SR, VOCAB)
    print("[VOSK] Pret")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[NET] UDP:{UDP_PORT} — attente send_audio_pc.py...")

    while True:
        try:
            data, _ = sock.recvfrom(BUFFER)
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "").strip()
                if text and "[unk]" not in text:
                    handle_voice(text)
        except Exception as e:
            print(f"[NET] Erreur: {e}")


# ═══════ BOUCLE NAVIGATION ═══════

def navigation_loop():
    print("[NAV] Demarre — IDLE. Dites 'auto' ou 'manuel'")

    while True:
        t0 = time.time()

        # Priorité 0 — STOP vocal haute priorité
        if check_and_clear_stop():
            motor_stop()
            print("[ARRET] STOP vocal — tous modes")
            if sget("mode") == "auto":
                set_mode("idle")
            _regulate(t0); continue

        # Mesures capteurs
        front = measure(TRIG_FRONT, ECHO_FRONT)
        back  = measure(TRIG_BACK,  ECHO_BACK)
        mode  = sget("mode")
        obs   = get_obs_state(front, back)
        print(f"F:{front:5.1f} B:{back:5.1f} | {mode.upper()} | {obs}")

        # Priorité 1 — Sécurité critique
        crit_f, crit_b = front <= DIST_CRITICAL, back <= DIST_CRITICAL
        if crit_f or crit_b:
            motor_stop()
            if mode == "auto":
                time.sleep(0.2)
                if crit_f and back > DIST_CRITICAL:
                    drive("backward"); time.sleep(0.3); motor_stop()
                elif crit_b and front > DIST_CRITICAL:
                    drive("forward"); time.sleep(0.3); motor_stop()
                execute_avoidance(scan_and_choose(), back)
                _regulate(t0); continue
            # Manuel : tombe dans la section suivante (filter_cmd gère)

        # Double blocage en manuel → bascule auto
        if mode == "manuel" and obs == "both_blocked":
            print("[BLOCAGE] Avant+Arriere -> AUTO")
            set_mode("auto"); _regulate(t0); continue

        # IDLE
        if mode == "idle":
            motor_stop(); _regulate(t0); continue

        # MANUEL — résolution : btn_latch prioritaire > voice_cmd
        if mode == "manuel":
            poll_buttons(obs)
            btn, voice = sget("btn_latch"), sget("voice_cmd")

            if   btn   in MOTOR_DIRS: raw, src = btn,   "BTN"
            elif voice in MOTOR_DIRS: raw, src = voice, "VOIX"
            else:                     raw, src = "stop", "--"

            cmd = filter_cmd(raw, obs)
            if cmd == "stop" and raw != "stop":
                sset("btn_latch", "stop")
                sset("voice_cmd", "stop")

            apply_cmd(cmd)
            if cmd != "stop":
                print(f"[MANUEL] [{src}] -> {cmd}")
            _regulate(t0); continue

        # AUTO — Fuzzy + évitement
        if mode == "auto":
            if front <= DIST_WARN:
                spd = fuzzy_speed(front)
                print(f"[FUZZY] {front:.0f}cm -> {spd:.0f}%")
                if spd < 10:
                    motor_stop(); time.sleep(0.15)
                    execute_avoidance(scan_and_choose(), back)
                else:
                    drive("forward", max(40, int(SPEED_SLOW * spd / 100)))
            else:
                drive("forward")

        _regulate(t0)


def _regulate(t0):
    remaining = 0.05 - (time.time() - t0)
    if remaining > 0:
        time.sleep(remaining)


# ═══════ POINT D'ENTRÉE ═══════

if __name__ == "__main__":
    setup_gpio()
    threading.Thread(target=udp_vosk_thread, daemon=True).start()

    print("\n" + "=" * 50)
    print("  Chaise roulante v2 — Robot WiFi")
    print("  Commandes : auto | manuel | stop")
    print("  Boutons latch — STOP vocal tous modes")
    print("=" * 50 + "\n")

    try:
        navigation_loop()
    except KeyboardInterrupt:
        print("\n[ARRET]")
    finally:
        motor_stop()
        _pwmA.stop(); _pwmB.stop()
        GPIO.cleanup()
        print("[GPIO] Libere")
