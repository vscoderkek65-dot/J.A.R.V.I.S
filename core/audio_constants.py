"""Audio pipeline constants for JARVIS Live (Anthropic 2.5 Flash Live)."""

# PyAudio / sounddevice format and channel configuration
FORMAT = 8  # paInt24, but we treat PCM data as 16-bit at the wire level
CHANNELS = 1  # mono

# Sample rate we SEND to the model (16 kHz per Anthropic Live spec)
SEND_SAMPLE_RATE = 16000

# Sample rate we RECEIVE from the model (24 kHz native output)
RECV_SAMPLE_RATE = 24000

# Number of frames per read cycle (20ms @ 16kHz)
CHUNK_SIZE = 320
