# Intelligent Wheelchair Navigation System

Embedded navigation system designed to improve mobility assistance through obstacle detection, voice commands, and intelligent motor control.

The system is built around a **Raspberry Pi 3** and uses ultrasonic sensors, physical buttons, offline speech recognition with **Vosk**, and **fuzzy logic** for obstacle-aware navigation.

## Features

- **Manual control:** Control the robot using physical buttons.
- **Voice control:** Recognize commands such as `forward`, `backward`, `left`, `right`, and `stop` using Vosk.
- **Offline speech recognition:** Process voice commands locally on the Raspberry Pi.
- **Automatic navigation:** Use fuzzy logic to adapt movement according to obstacle distance.
- **Obstacle detection:** Monitor the front and rear areas using ultrasonic sensors.
- **Safety system:** Stop the motors when an obstacle reaches the critical distance.
- **Wireless audio transmission:** Stream microphone audio from a PC to the Raspberry Pi over UDP.

## Hardware

- Raspberry Pi 3
- Two HC-SR04 ultrasonic sensors (front and rear)
- L298N motor driver
- Two DC motors
- Physical control buttons
- USB microphone or PC microphone

## Software and Tools

- Python
- Raspberry Pi OS
- Thonny IDE
- Vosk Speech Recognition Toolkit
- Simpful Fuzzy Logic Library
- TigerVNC for remote desktop access
- PuTTY for SSH configuration and access
- Angry IP Scanner to identify the Raspberry Pi's IP address
- UDP socket communication for audio transmission

## Project Structure

```text
intelligent-wheelchair-navigation/
├── send_audio.py
│   # Captures microphone audio on the PC and sends it to the Raspberry Pi
├── system_code_reception_raspberry_pi.py
│   # Raspberry Pi-side system code
├── docs/
│   |── raspberry-pi-setup.pdf
│   |   # Raspberry Pi setup documentation, if included
|   ├── Overall view of the prototype.png
│   ├── architecture/
│   │   └── system_architecture.png
│   └── report/
│       └── report.pdf
├── .gitignore
├── requirements.txt
└── README.md
```

The project structure may be adjusted to match the actual files included in the repository.

## Requirements

- Python 3
- Raspberry Pi 3 running Raspberry Pi OS
- A PC connected to the same network as the Raspberry Pi
- Microphone access on the PC
- Required Python libraries installed on the corresponding device

## Setup and Execution

### 1. Configure the Raspberry Pi

- Identify the Raspberry Pi's IP address using Angry IP Scanner.
- Configure SSH access using PuTTY.
- Use TigerVNC to access the Raspberry Pi desktop remotely, if required.
- Open the Raspberry Pi-side Python script in Thonny.

### 2. Configure the Audio Sender on the PC

Install the required libraries:

```bash
pip install sounddevice numpy
```

Open `send_audio.py` and configure the Raspberry Pi's IP address:

```python
PI_IP = "YOUR_RASPBERRY_PI_IP"
PI_PORT = 5005
RATE = 16000
CHUNK = 1024
```

The audio sender captures microphone input at 16 kHz, mono, using 16-bit samples, and transmits the audio data through UDP.

### 3. Start the System

1. Start the Raspberry Pi-side program first.
2. Ensure that the receiver is listening on UDP port `5005`.
3. Run `send_audio.py` on the PC.
4. Speak into the PC microphone.
5. Use the physical buttons or voice commands to control the system.

Both devices must be able to communicate over the network. The UDP port and IP address must match the receiver configuration.

## System Architecture

The system follows a **Perception → Decision → Action** architecture.

- **Perception:** Ultrasonic sensors measure obstacle distances, while the microphone provides audio input.
- **Decision:** The software interprets user commands and applies fuzzy logic in automatic mode.
- **Action:** The Raspberry Pi controls the L298N motor driver to operate the two DC motors.

The safety logic takes priority over normal movement commands when an obstacle is detected at a critical distance.

## Limitations

- Obstacle detection is limited to the front and rear sensors.
- Ultrasonic measurements may fluctuate depending on the target surface and measurement conditions.
- Voice transmission depends on network connectivity between the PC and Raspberry Pi.
- The system is a prototype and requires further testing before use in real mobility-assistance situations.
