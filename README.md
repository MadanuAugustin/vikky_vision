# Vikki Vision

Vikki Vision is a real-time voice and vision assistant built on Google's **Gemini 3.8 Live** API.
It streams your webcam and microphone to Gemini, and **Vikki** talks back through your speakers —
so you can hold a natural spoken conversation with an assistant that can see what's in front of the camera.

## Features

- **Live camera streaming** – sends a frame from your webcam every second so Vikki can see you and your surroundings.
- **Voice conversation** – speak naturally; Vikki answers out loud. No typing needed.
- **Interruptions** – talk over Vikki at any time and she stops and listens.
- **Echo protection** – Vikki's own voice coming out of the speakers isn't sent back to her, so she doesn't answer herself.
- **Named assistant** – she introduces herself as Vikki and responds to "Hi Vikki".
- **Logging** – every session is logged, including transcripts of what you and Vikki said.

## Requirements

- Windows, macOS or Linux with a **webcam**, **microphone** and **speakers/headphones**
- **Python 3.11 or newer** (tested on Python 3.14)
- A **Gemini API key** from [Google AI Studio](https://aistudio.google.com/apikey)

## Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/MadanuAugustin/vikky_vision.git
   cd vikky_vision
   ```

2. **Create and activate a virtual environment**

   Windows (PowerShell):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   > If PowerShell says *"running scripts is disabled on this system"*, run
   > `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again.

   macOS / Linux:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install the dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Add your Gemini API key**

   Copy `.env.example` to `.env`:

   ```powershell
   copy .env.example .env      # Windows
   ```

   ```bash
   cp .env.example .env        # macOS / Linux
   ```

   Then open `.env` and replace `your-gemini-api-key-here` with your key:

   ```
   GEMINI_API_KEY=your-actual-key
   ```

   `.env` is listed in `.gitignore`, so your key is never committed.

## Running Vikki Vision

With the virtual environment active:

```bash
python liveAPI.py
```

- The camera turns on (this can take a few seconds) and Vikki starts listening.
- Just talk — try *"Hi Vikki, what's your name?"* or *"Vikki, what do you see?"*
- To interrupt her, simply start speaking while she's talking.
- Press **Ctrl+C** to quit.

## Logs

Each run writes a log file to:

```
logs/<YYYY-MM-DD>/vikki_vision_<HH-MM-SS>.log
```

The log records connection events, camera/microphone status, errors, and a transcript of the conversation
(`User said: ...` / `Vikki said: ...`).

## Configuration

Optional settings in `.env`:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | – | Your Gemini API key (required) |
| `GEMINI_MODEL` | `models/gemini-3.8-live` | Gemini Live model to use |
| `BARGE_IN_MIN_RMS` | `600` | How loud you must speak to interrupt Vikki. Lower it if she doesn't stop when you talk; raise it if background noise cuts her off. |

## Troubleshooting

- **`GEMINI_API_KEY is not set`** – create `.env` as described in step 4.
- **`Could not open the default camera`** – close other apps using the webcam (Zoom, Teams, Camera) and check your OS camera privacy settings.
- **Vikki responds to things nobody said** – background noise or speaker echo is reaching the mic. Using headphones gives the best experience.

## Project structure

```
liveAPI.py         Main application: camera + microphone streaming and audio playback
logger.py          Logging setup (per-run log files under logs/)
requirements.txt   Python dependencies
.env.example       Template for the .env file holding your API key
```
