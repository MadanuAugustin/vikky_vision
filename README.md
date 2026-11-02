# Vikki Vision

Vikki Vision is a real-time voice and vision assistant. Turn it on, and **Vikki** watches through your
webcam, listens through your microphone and talks back through your speakers — so you can hold a natural
spoken conversation with an assistant that can see what's in front of the camera.

## Features

- **Live camera streaming** – sends a frame from your webcam every second so Vikki can see you and your surroundings.
- **Live camera window** – your camera feed is shown on screen during the conversation, with a status line
  showing whether Vikki is listening or speaking.
- **Voice conversation** – speak naturally; Vikki answers out loud. No typing needed.
- **Interruptions** – talk over Vikki at any time and she stops and listens.
- **Echo protection** – Vikki's own voice coming out of the speakers isn't sent back to her, so she doesn't answer herself.
- **Named assistant** – she introduces herself as Vikki and responds to "Hi Vikki".
- **Logging** – technical events (connection, camera, microphone, errors) are logged for every session.
- **Conversation recording** – each session's conversation is saved as a table (CSV), together with the camera frames Vikki saw.

## Requirements

- Windows, macOS or Linux with a **webcam**, **microphone** and **speakers/headphones**
- **Python 3.11 or newer** (tested on Python 3.14)
- A **Vikki Vision API key**

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

3. **Install Vikki Vision and its dependencies**

   ```bash
   pip install -e .
   ```

   This installs the `vikki_vision` package from `src/` together with everything in `requirements.txt`,
   and adds the `vikki-vision` command. For development (includes the test tools), use `pip install -e ".[dev]"`.

4. **Add your API key**

   Copy `.env.example` to `.env`:

   ```powershell
   copy .env.example .env      # Windows
   ```

   ```bash
   cp .env.example .env        # macOS / Linux
   ```

   Then open `.env` and replace `your-api-key-here` with your key:

   ```
   VIKKI_API_KEY=your-actual-key
   ```

   `.env` is listed in `.gitignore`, so your key is never committed.

## Running Vikki Vision

From the project folder, with the virtual environment active:

```bash
vikki-vision
```

or, equivalently:

```bash
python -m vikki_vision
```

- A **Vikki Vision** window opens with your live camera feed (the camera can take a few seconds to start),
  and Vikki starts listening. The window shows whether Vikki is *listening* or *speaking*.
- Just talk — try *"Hi Vikki, what's your name?"* or *"Vikki, what do you see?"*
- To interrupt her, simply start speaking while she's talking.
- To quit, **close the camera window** or press **Q** / **Esc** while it is focused. **Ctrl+C** in the terminal also works.

## Logs

Each run writes a log file to:

```
logs/<YYYY-MM-DD>/vikki_vision_<HH-MM-SS>.log
```

The log records technical events only — connection status, camera/microphone status, interruptions and errors.
What you and Vikki say is not written to the log; it is stored in the `conversations/` folder (see below).

## Recorded conversations

Every session is saved to its own folder:

```
conversations/<YYYY-MM-DD>/<HH-MM-SS>/
    conversation.csv
    frames/frame_000001.jpg, frame_000002.jpg, ...
```

`conversation.csv` opens in Excel and has one row per line spoken:

| timestamp | speaker | text | camera_frame |
|---|---|---|---|
| 2026-11-02 10:20:59 | User | What's your name? | frames/frame_000016.jpg |
| 2026-11-02 10:20:59 | Vikki | I'm Vikki, your Vikki Vision assistant. How can I help you? | frames/frame_000016.jpg |

`camera_frame` is the camera image Vikki was looking at when that line was spoken. Frames are saved once per
second (about 100 MB per hour). The `conversations/` folder is excluded from git, since it contains personal data.

## Configuration

Optional settings in `.env`:

| Variable | Default | Description |
|---|---|---|
| `VIKKI_API_KEY` | – | Your API key (required) |
| `VIKKI_CAMERA_INDEX` | `0` | Which camera to use, if you have more than one |
| `VIKKI_FRAME_INTERVAL` | `1.0` | Seconds between camera frames sent to Vikki |
| `VIKKI_SHOW_PREVIEW` | `true` | Show the live camera window. Set to `false` to run without it. |
| `VIKKI_DATA_DIR` | current folder | Where the `logs/` and `conversations/` folders are created |
| `BARGE_IN_MIN_RMS` | `600` | How loud you must speak to interrupt Vikki. Lower it if she doesn't stop when you talk; raise it if background noise cuts her off. |

## Troubleshooting

- **`VIKKI_API_KEY is not set`** – create `.env` as described in step 4.
- **`Could not open camera 0`** – close other apps using the webcam (Zoom, Teams, Camera) and check your OS camera privacy settings.
- **Vikki responds to things nobody said** – background noise or speaker echo is reaching the mic. Using headphones gives the best experience.

## Running the tests

```bash
pip install -e ".[dev]"
pytest
```

## Project structure

```
vikky_vision/
├── src/vikki_vision/
│   ├── __main__.py            # `python -m vikki_vision`
│   ├── app.py                 # Entry point: loads settings, sets up logging, starts the session
│   ├── config.py              # Settings loaded from environment variables / .env
│   ├── assistant/
│   │   ├── client.py          # API client and live session configuration
│   │   ├── prompts.py         # Vikki's identity and behaviour instructions
│   │   └── session.py         # Live conversation: runs camera, mic, speaker and response tasks
│   ├── audio/
│   │   ├── microphone.py      # Microphone input
│   │   ├── speaker.py         # Audio playback that can be stopped instantly
│   │   └── barge_in.py        # Detects the user talking over Vikki
│   ├── vision/
│   │   ├── camera.py          # Webcam capture on a background thread
│   │   └── preview.py         # Live camera window (drawn from the main thread)
│   ├── storage/
│   │   └── session_store.py   # Saves conversation.csv and camera frames per session
│   └── utils/
│       └── logger.py          # Per-run log files (technical events only)
├── tests/                     # Unit tests (pytest)
├── pyproject.toml             # Package metadata, dependencies and the `vikki-vision` command
├── requirements.txt           # Pinned runtime dependencies
└── .env.example               # Template for the .env file holding your API key
```
