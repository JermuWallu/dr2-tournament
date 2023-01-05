import wave
import pyaudio

from timerecorder.log import getLogger

CHUNK = 1024

logger = getLogger(__name__)


def play_wave(wave_file: str) -> None:
    try:
        file = wave.open(wave_file, "rb")
        audio = pyaudio.PyAudio()

        stream = audio.open(format=audio.get_format_from_width(file.getsampwidth()),
                            channels=file.getnchannels(),
                            rate=file.getframerate(),
                            output=True)

        data = file.readframes(CHUNK)
        while len(data):
            stream.write(data)
            data = file.readframes(CHUNK)

        stream.stop_stream()
        stream.close()

        audio.terminate()
    except:  # pylint: disable=bare-except
        logger.debug("Failed to play sound")
