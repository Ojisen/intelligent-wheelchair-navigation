"""
send_audio_pc.py  — À lancer sur le PC (Thonny)
=================================================
Capture le micro intégré du PC et envoie l'audio
brut en UDP vers le Raspberry Pi.

Prérequis PC :
    pip install sounddevice numpy

Utilisation :
    1. Lancer d'abord receive_audio_pi.py sur le Pi
    2. Lancer ce script sur le PC
    3. Parler dans le micro du PC
"""

import sounddevice as sd
import socket
import numpy as np
import sys

# ── CONFIGURATION ──────────────────────────────────────────
PI_IP    = "192.168.1.8"   # IP fixe du Raspberry Pi
PI_PORT  = 5005            # Port UDP (même valeur sur le Pi)
RATE     = 16000           # Vosk exige 16000 Hz
CHUNK    = 1024            # Taille des blocs audio envoyés
# ──────────────────────────────────────────────────────────


def find_default_input():
    """
    Cherche le micro par défaut du PC.
    Affiche la liste complète pour aider au diagnostic.
    """
    print("Périphériques audio disponibles :")
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        marker = ">>>" if d["max_input_channels"] > 0 else "   "
        print(f"  {marker} [{i}] {d['name']}  "
              f"(entrées: {d['max_input_channels']}, "
              f"sr: {int(d['default_samplerate'])}Hz)")

    # Micro par défaut du système
    default = sd.default.device[0]
    info    = sd.query_devices(default)
    print(f"\nMicro sélectionné : [{default}] {info['name']}")
    return default


def main():
    device_id = find_default_input()
    sock      = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    packets_sent = 0

    def callback(indata, frames, time_info, status):
        nonlocal packets_sent
        if status:
            print(f"[AUDIO] {status}")
        # Envoi du bloc audio brut (int16, 16000 Hz, mono)
        sock.sendto(indata.tobytes(), (PI_IP, PI_PORT))
        packets_sent += 1
        # Affichage de progression toutes les 50 paquets (~3 sec)
        if packets_sent % 50 == 0:
            print(f"[NET] {packets_sent} paquets envoyés → {PI_IP}:{PI_PORT}")

    print(f"\n[NET] Envoi vers {PI_IP}:{PI_PORT}")
    print("[MIC] Parle dans le micro — Ctrl+C pour arrêter\n")

    try:
        with sd.InputStream(
                device=device_id,
                samplerate=RATE,
                channels=1,
                dtype="int16",
                blocksize=CHUNK,
                callback=callback):
            while True:
                sd.sleep(1000)

    except KeyboardInterrupt:
        print(f"\n[ARRET] {packets_sent} paquets envoyés au total")
        sock.close()

    except sd.PortAudioError as e:
        print(f"[ERREUR] Micro inaccessible : {e}")
        print("Vérifie que le micro est branché et sélectionné.")
        sys.exit(1)


if __name__ == "__main__":
    main()